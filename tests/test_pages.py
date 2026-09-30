"""Every page renders, for every kind of result, using an in-memory stand-in for Postgres.

Tenant isolation itself is tested against real Postgres in test_isolation.py.
"""

from contextlib import contextmanager

import pytest
from conftest import make_order
from fastapi.testclient import TestClient

from pack_manager.models import Decision
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.vision.oracle import OraclePerceiver


class FakeStore:
    def __init__(self):
        self.orders, self.records, self.images = {}, {}, {}

    # the functions app.main calls, scoped by org like RLS would
    def resolve_code(self, cur, code):
        return {"alpha-demo": {"organization_id": "org_demo_alpha", "operator_label": "op_alpha"},
                "bravo-demo": {"organization_id": "org_demo_bravo", "operator_label": "op_bravo"}}.get(code)

    def org_name(self, cur, org):
        return org

    VIEWS = {"todo": lambda d: d in (None, "PENDING", "UNCERTAIN"), "done": lambda d: d in ("SEAL", "STOP_AND_FIX"),
             "all": lambda d: True}

    def _orders_with_latest(self, cur, q):
        rows = []
        for (org, order_id), o in self.orders.items():
            if org != cur or (q and q.lower() not in order_id.lower()):
                continue
            recs = [r for r in self.records.values() if r.organization_id == cur and r.subject["order_id"] == order_id]
            last = max(recs, key=lambda r: r.captured_at, default=None)
            rows.append({"order": o, "record_id": last and last.record_id,
                         "decision": last and last.outcome.decision.value})
        return rows

    def list_orders(self, cur, q=None, view="all", limit=200):
        return [r for r in self._orders_with_latest(cur, q) if self.VIEWS[view](r["decision"])][:limit]

    def order_counts(self, cur, q=None):
        rows = self._orders_with_latest(cur, q)
        return {view: sum(1 for r in rows if keep(r["decision"])) for view, keep in self.VIEWS.items()}

    def get_order(self, cur, order_id):
        return self.orders.get((cur, order_id))

    def upsert_order(self, cur, order, source="demo"):
        self.orders[(cur, order.order_id)] = order

    def _retried(self, r):
        """A pending record that was checked again (store._RETRIED)."""
        return r.outcome.decision.value == "PENDING" and self.find_retry(r.organization_id, r.record_id) is not None

    def list_records(self, cur, decision=None, order_id=None, unit_id=None, limit=200, query=None, since=None):
        rows = [
            {"record_id": r.record_id, "order_id": r.subject["order_id"], "decision": r.outcome.decision.value,
             "status": r.status.value, "captured_at": r.captured_at, "operator_label": r.operator_label,
             "overrides": len(r.box_overrides), "retried": self._retried(r)}
            for r in self.records.values()
            if r.organization_id == cur
            and (order_id is None or r.subject["order_id"] == order_id)
            and (unit_id is None or r.subject.get("unit_id") == unit_id)
            and (decision is None or r.outcome.decision.value == decision)
            and (query is None or query.lower() in (r.subject["order_id"] + r.record_id).lower())
            and (since is None or r.captured_at >= since)
        ]
        if decision == "PENDING":
            rows = [row for row in rows if not row["retried"]]
        rows.sort(key=lambda row: (row["captured_at"], row["record_id"]), reverse=since is None)  # like the SQL
        return rows[:limit]

    def find_retry(self, cur, record_id, lock=False):
        found = sorted((r.captured_at, r.record_id) for r in self.records.values()
                       if r.organization_id == cur and (r.observations or {}).get("retry_of") == record_id)
        return found[0][1] if found else None

    def counts_by_decision(self, cur):
        counts = {}
        for r in self.records.values():
            if r.organization_id == cur:
                key = "RETRIED" if self._retried(r) else r.outcome.decision.value
                counts[key] = counts.get(key, 0) + 1
        return counts

    def count_ai_checks_since(self, cur, since):
        """Boxes the model answered for (store.count_ai_checks_since)."""
        def answered(r):
            first = r.overrides[0].original_decision if r.overrides else r.outcome.decision
            return first.value != "PENDING" and not (r.observations or {}).get("cached_response")
        return sum(1 for r in self.records.values()
                   if r.organization_id == cur and r.captured_at >= since and answered(r))

    def save_record(self, cur, record, photos):
        self.records[record.record_id] = record
        for p in photos:
            self.images[p.image_id] = (record.organization_id, p.mime, p.jpeg, p.sha256, record.record_id)

    def find_image_uses(self, cur, sha256s):
        return [{"sha256": sha, "record_id": rid, "order_id": self.records[rid].subject["order_id"]}
                for org, _, _, sha, rid in self.images.values() if org == cur and sha in sha256s]

    def update_record(self, cur, record, prior_hash):
        current = self.records.get(record.record_id)
        if not current or current.organization_id != cur or current.content_hash != prior_hash:
            return False
        self.records[record.record_id] = record
        return True

    def get_record(self, cur, record_id):
        r = self.records.get(record_id)
        return r if r and r.organization_id == cur else None

    def get_image(self, cur, image_id):
        found = self.images.get(image_id)
        return (found[1], found[2]) if found and found[0] == cur else None

    def get_records(self, cur, ids):
        return {rid: r for rid in ids if (r := self.get_record(cur, rid))}

    def image_sizes_many(self, cur, ids):
        return {rid: self.image_sizes(cur, rid) for rid in ids}

    def image_sizes(self, cur, record_id):
        return {iid: len(v[2]) for iid, v in self.images.items() if v[0] == cur and v[4] == record_id}

    def records_page(self, cur, since, after, limit):
        """store.records_page: in the order records were saved (a dict keeps insertion order)."""
        ids = [r.record_id for r in self.records.values() if r.organization_id == cur]
        if after is not None:
            if after not in ids:
                return None
            ids = ids[ids.index(after) + 1:]
        return [rid for rid in ids if since is None or self.records[rid].captured_at >= since][:limit]

    def legacy_record_ids(self, cur):
        return [r.record_id for r in self.records.values() if r.organization_id == cur and r.record_id.startswith("PCK-")]


# Every app.store function the web app calls; the fixture swaps each for the FakeStore's.
STORE_FUNCTIONS = ["resolve_code", "org_name", "list_orders", "order_counts", "get_order", "list_records",
                   "counts_by_decision", "save_record", "update_record", "get_record", "get_image",
                   "find_image_uses", "find_retry", "count_ai_checks_since", "upsert_order",
                   "image_sizes", "records_page", "legacy_record_ids", "get_records", "image_sizes_many"]


class FakeDb:
    @contextmanager
    def org(self, org_id):
        yield org_id

    @contextmanager
    def anonymous(self):
        yield None


@pytest.fixture
def client(monkeypatch, catalogue):
    return make_client(monkeypatch, catalogue)


def make_client(monkeypatch, catalogue):
    """The app on the in-memory store, signed out. Shared with test_web_hardening.py."""
    import app.main as main

    fake = FakeStore()
    for name in STORE_FUNCTIONS:
        monkeypatch.setattr(main.store, name, getattr(fake, name))
    monkeypatch.setattr(main, "db", lambda: FakeDb())
    monkeypatch.setattr(main, "org_catalogue", lambda org: (catalogue, None))
    # Never call the real model from tests, even when .env holds a key: no key means PENDING.
    monkeypatch.setattr(main.settings, "gemini_api_key", None)
    c = TestClient(main.app)
    c.fake = fake
    return c


def add_order(fake, *lines, order_id="ORD-1", org="org_demo_alpha"):
    order = make_order(*lines, order_id=order_id).model_copy(update={"organization_id": org})
    fake.orders[(org, order_id)] = order
    return order


def test_login_required_and_login_flow(client):
    front = client.get("/", follow_redirects=False)  # signed out: the public front page
    assert front.status_code == 200 and "Try it with a demo company" in front.text and "Sign out" not in front.text
    assert client.get("/records", follow_redirects=False).status_code == 303
    assert client.post("/login", data={"code": "wrong"}).status_code == 401
    assert client.post("/login", data={"code": "alpha-demo"}).status_code == 200


@pytest.mark.parametrize("seen,expected", [
    ({"CAP-BLU": 1}, "Seal the box"),
    ({"CAP-RED": 1}, "Stop and fix"),
    ({"LAMP": 1, "CABLE": 1}, None),
])
def test_record_pages_render(client, sharp_photo, catalogue, settings, seen, expected):
    fake = client.fake
    order = add_order(fake, *([("CAP-BLU", 1)] if "LAMP" not in seen else [("LAMP", 1)]))
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(order, prepared, catalogue, OraclePerceiver(seen), settings, operator_label="op_alpha")
    fake.save_record(None, record, prepared)

    client.post("/login", data={"code": "alpha-demo"})
    html = client.get(f"/records/{record.record_id}").text
    assert expected is None or expected in html
    assert "Evidence details" in html and record.content_hash in html and "matches record" in html
    # The printed sheet says how anyone can check the record, and shows the phone original's hash.
    assert "data-print" in html and f"check-record {record.record_id}.json" in html
    assert record.images[0].original_sha256 in html
    assert client.get(f"/images/{record.images[0].image_id}").status_code == 200
    for path in ["/", "/records", "/orders/ORD-1", f"/api/records/{record.record_id}"]:
        assert client.get(path).status_code == 200, path
    dl = client.get(f"/api/records/{record.record_id}?download=1")
    assert "attachment" in dl.headers["content-disposition"]
    from pack_manager.evidence import verify
    from pack_manager.models import EvidenceRecord
    assert verify(EvidenceRecord.model_validate_json(dl.content))  # the downloaded file verifies on its own


def test_verify_upload_creates_record_and_override_keeps_history(client, sharp_photo):
    add_order(client.fake, ("CAP-BLU", 1))
    client.post("/login", data={"code": "alpha-demo"})
    # No API key in tests: the check fails open to a pending record.
    resp = client.post("/orders/ORD-1/verify", files={"photos": ("box.jpg", sharp_photo, "image/jpeg")},
                       follow_redirects=False)
    assert resp.status_code == 303
    record_url = resp.headers["location"]
    html = client.get(record_url).text
    assert "Needs your decision" in html and "Record your decision" in html

    rid = record_url.rsplit("/", 1)[1]
    client.post(f"/records/{rid}/decision", data={"decision": "SEAL", "reason_code": "agent_unavailable",
                                                   "note": "checked by hand"})
    rec = client.fake.records[rid]
    assert rec.outcome.decision == Decision.SEAL and rec.overrides[0].original_decision == Decision.PENDING
    assert "Decided by op_alpha" in client.get(record_url).text


def test_blurry_upload_is_rejected_then_can_be_forced(client):
    import numpy as np
    from conftest import jpeg_bytes

    add_order(client.fake, ("CAP-BLU", 1))
    client.post("/login", data={"code": "alpha-demo"})
    flat = jpeg_bytes(np.full((1200, 1600, 3), 128))
    html = client.post("/orders/ORD-1/verify", files={"photos": ("b.jpg", flat, "image/jpeg")}).text
    assert "The photo could be clearer" in html and "Use these photos anyway" in html
    stash = html.split('name="stash" value="')[1].split('"')[0]
    resp = client.post("/orders/ORD-1/verify", data={"stash": stash}, follow_redirects=False)
    assert resp.status_code == 303


def test_other_org_gets_404(client, sharp_photo, catalogue, settings):
    order = add_order(client.fake, ("CAP-BLU", 1))
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings, operator_label="a")
    client.fake.save_record(None, record, prepared)
    client.post("/login", data={"code": "bravo-demo"})
    assert client.get(f"/records/{record.record_id}").status_code == 404
    assert client.get(f"/images/{record.images[0].image_id}").status_code == 404
    assert client.get("/orders/ORD-1").status_code == 404


def test_same_photo_for_another_order_is_flagged(client, sharp_photo):
    add_order(client.fake, ("CAP-BLU", 1), order_id="ORD-1")
    add_order(client.fake, ("CAP-BLU", 1), order_id="ORD-2")
    client.post("/login", data={"code": "alpha-demo"})
    upload = {"photos": ("box.jpg", sharp_photo, "image/jpeg")}
    first = client.post("/orders/ORD-1/verify", files=upload, follow_redirects=False).headers["location"]
    again = client.post("/orders/ORD-1/verify", files=upload, follow_redirects=False).headers["location"]
    other = client.post("/orders/ORD-2/verify", files=upload, follow_redirects=False).headers["location"]

    def reuse(url):
        rec = client.fake.records[url.rsplit("/", 1)[1]]
        return next(c for c in rec.checks if c.check_key == "photo_reuse")

    assert reuse(first).verdict.value == "PASS"
    assert reuse(again).verdict.value == "PASS"  # re-checking the same order is fine
    assert reuse(other).verdict.value == "UNCERTAIN" and "ORD-1" in reuse(other).detail


def test_daily_limit_fails_open_to_pending(client, sharp_photo, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main.settings, "daily_checks_per_org", 1)
    monkeypatch.setattr(main, "perceiver", lambda: OraclePerceiver({"CAP-BLU": 1}))
    add_order(client.fake, ("CAP-BLU", 1))
    client.post("/login", data={"code": "alpha-demo"})
    upload = {"photos": ("box.jpg", sharp_photo, "image/jpeg")}
    client.post("/orders/ORD-1/verify", files=upload)  # the model answers: one AI check used
    url = client.post("/orders/ORD-1/verify", files=upload, follow_redirects=False).headers["location"]
    rec = client.fake.records[url.rsplit("/", 1)[1]]
    assert rec.outcome.decision == Decision.PENDING
    assert "1 AI checks. Check this box by hand." in client.get(url).text


def upload_csv(client, rows):
    data = "\n".join(rows).encode()
    return client.post("/orders/import", files={"file": ("orders.csv", data, "text/csv")}).text


def test_orders_csv_import(client):
    client.post("/login", data={"code": "alpha-demo"})
    assert "File format" in client.get("/orders/import").text
    add_order(client.fake, ("CAP-BLU", 1), order_id="ORD-7")
    html = upload_csv(client, [
        "order_id,order_lines,channel,organization_id",
        "ORD-7,CAP-RED:2,shopify,org_demo_bravo",  # updates ORD-7; the org column is ignored
        "ORD-8,LAMP:1;CABLE:1,,",
        "ORD-9,not a line,,",
        ",CAP-RED:1,,",
        "ORD-8,CAP-RED:1,,",
        "ORD-10,MYSTERY-SKU:1,,",
    ])
    assert "3 orders imported" in html and "1 already existed" in html
    assert "Row 4: order_lines must look like" in html and "Row 5: no order_id." in html
    assert "ORD-8 appears twice" in html and "MYSTERY-SKU" in html
    orders = client.fake.orders
    assert ("org_demo_bravo", "ORD-7") not in orders
    assert orders[("org_demo_alpha", "ORD-7")].lines[0].sku == "CAP-RED"
    assert orders[("org_demo_alpha", "ORD-7")].organization_id == "org_demo_alpha"
    assert ("org_demo_alpha", "ORD-9") not in orders


def test_orders_csv_import_rejects_bad_files(client):
    client.post("/login", data={"code": "alpha-demo"})
    assert "needs the columns order_id and order_lines" in upload_csv(client, ["id,items", "1,2"])
    bad = client.post("/orders/import", files={"file": ("x.csv", bytes([0xff, 0xfe, 0x00]), "text/csv")})
    assert "Save the file as CSV (UTF-8)" in bad.text



def test_order_tabs_and_record_search(client, sharp_photo, catalogue, settings):
    fake = client.fake
    order = add_order(fake, ("CAP-BLU", 1), order_id="ORD-77")
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings, operator_label="op_alpha")
    fake.save_record(None, record, prepared)
    client.post("/login", data={"code": "alpha-demo"})

    assert "ORD-77" in client.get("/?view=done").text  # its latest record is a SEAL
    assert "ORD-77" not in client.get("/?view=todo").text
    assert client.get("/?view=nonsense").status_code == 200

    assert record.record_id in client.get("/records?q=ord-77").text
    assert 'No records match "nope"' in client.get("/records?q=nope").text


def _pending_box(client, sharp_photo, order_id="ORD-1"):
    """No API key in tests, so an upload fails open to a pending record."""
    add_order(client.fake, ("CAP-BLU", 1), order_id=order_id)
    client.post("/login", data={"code": "alpha-demo"})
    url = client.post(f"/orders/{order_id}/verify", files={"photos": ("box.jpg", sharp_photo, "image/jpeg")},
                      follow_redirects=False).headers["location"]
    return url.rsplit("/", 1)[1]


def test_retry_ai_check_makes_a_linked_record(client, sharp_photo, monkeypatch):
    import app.main as main

    rid = _pending_box(client, sharp_photo)
    assert "Retry AI check" in client.get(f"/records/{rid}").text
    before = client.fake.records[rid]

    monkeypatch.setattr(main, "perceiver_for", lambda org: OraclePerceiver({"CAP-RED": 1}))
    url = client.post(f"/records/{rid}/retry", follow_redirects=False).headers["location"]
    new = client.fake.records[url.rsplit("/", 1)[1]]
    assert new.record_id != rid and new.outcome.decision == Decision.STOP_AND_FIX
    assert new.observations["retry_of"] == rid and "disagreement" not in new.observations
    assert [i.sha256 for i in new.images] == [i.sha256 for i in before.images]  # the same photos
    assert client.fake.records[rid] == before  # the original record is untouched
    assert "second AI check" in client.get(url).text
    assert "Checked again" in client.get(f"/records/{rid}").text


def test_retry_flags_disagreement_with_the_hand_decision(client, sharp_photo, monkeypatch):
    import app.main as main

    rid = _pending_box(client, sharp_photo)
    client.post(f"/records/{rid}/decision", data={"decision": "SEAL", "reason_code": "agent_unavailable"})
    monkeypatch.setattr(main, "perceiver_for", lambda org: OraclePerceiver({"CAP-RED": 1}))
    url = client.post(f"/records/{rid}/retry", follow_redirects=False).headers["location"]
    new = client.fake.records[url.rsplit("/", 1)[1]]
    assert new.observations["disagreement"]["human_decision"] == "SEAL"
    assert "The AI disagrees with the decision made by hand" in client.get(url).text


def test_retry_only_for_boxes_the_ai_did_not_answer(client, sharp_photo, catalogue, settings):
    order = add_order(client.fake, ("CAP-BLU", 1))
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings, operator_label="op_alpha")
    client.fake.save_record(None, record, prepared)
    client.post("/login", data={"code": "alpha-demo"})
    assert "Retry AI check" not in client.get(f"/records/{record.record_id}").text
    count = len(client.fake.records)
    client.post(f"/records/{record.record_id}/retry")
    assert len(client.fake.records) == count


def test_rerun_refuses_photos_that_do_not_match_the_record(sharp_photo, catalogue, settings):
    from pack_manager.pipeline import rerun_box

    order = make_order(("CAP-BLU", 1))
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings, operator_label="op")
    with pytest.raises(ValueError, match="doesn't match its hash"):
        rerun_box(record, [prepared[0].jpeg + b"x"], catalogue, OraclePerceiver({}), settings, retried_by="op")


def test_app_url_is_the_admin_url_as_pack_app(tmp_path):
    from app.migrate import app_url_from_admin, write_env_value

    admin = "postgresql://neondb_owner:s3cret@ep-cool-1-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert app_url_from_admin(admin, "p@ss/w:rd") == (
        "postgresql://pack_app:p%40ss%2Fw%3Ard@ep-cool-1-pooler.ap-southeast-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require")
    assert app_url_from_admin("postgresql://postgres:pw@localhost:5432/pack_manager", "x") == \
        "postgresql://pack_app:x@localhost:5432/pack_manager"

    env = tmp_path / ".env"
    env.write_text("# keep me\nDATABASE_URL=\nGEMINI_MODEL=m\n", encoding="utf-8")
    write_env_value("DATABASE_URL", "postgresql://a", env)
    write_env_value("NEW_KEY", "1", env)
    assert env.read_text(encoding="utf-8") == "# keep me\nDATABASE_URL=postgresql://a\nGEMINI_MODEL=m\nNEW_KEY=1\n"


def test_records_csv_uses_the_organisers_columns_first(client, sharp_photo):
    import csv as csvlib

    from pack_manager.export import SAMPLE_COLUMNS

    rid = _pending_box(client, sharp_photo, order_id="=HYPERLINK(1)")
    client.post(f"/records/{rid}/decision", data={"decision": "SEAL", "reason_code": "agent_unavailable", "note": ""})
    resp = client.get("/api/records.csv")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    rows = list(csvlib.DictReader(resp.text.splitlines()))
    assert list(rows[0])[: len(SAMPLE_COLUMNS)] == SAMPLE_COLUMNS
    row = rows[0]
    assert row["order_id"] == "'=HYPERLINK(1)"  # not run as a formula in a spreadsheet
    assert (row["agent_decision"], row["final_decision"], row["decided_by"]) == ("PENDING", "SEAL", "operator")
    assert row["operator_verdict"] == "seal" and row["hash_verified"] == "yes"
    assert row["order_lines"] == "CAP-BLU:1" and row["photo_refs"].startswith("images/")

    client.get("/logout")
    assert client.get("/api/records.csv").status_code == 401


def test_api_since_returns_a_cursor(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    captured = client.fake.records[rid].captured_at
    body = client.get("/api/records", params={"since": captured.isoformat()}).json()
    assert [r["record_id"] for r in body["records"]] == [rid] and body["next_since"]
    later = captured.replace(year=captured.year + 1).isoformat()
    assert client.get("/api/records", params={"since": later}).json()["records"] == []
    assert client.get("/api/records", params={"since": "not-a-date"}).status_code == 422
