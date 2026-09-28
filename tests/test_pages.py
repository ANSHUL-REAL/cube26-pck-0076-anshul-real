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

    def list_orders(self, cur, q=None, limit=200):
        return [{"order": o, "record_id": None, "decision": None} for (org, _), o in self.orders.items() if org == cur]

    def get_order(self, cur, order_id):
        return self.orders.get((cur, order_id))

    def list_records(self, cur, decision=None, order_id=None, unit_id=None, limit=200):
        return [
            {"record_id": r.record_id, "order_id": r.subject["order_id"], "decision": r.outcome.decision.value,
             "status": r.status.value, "captured_at": r.captured_at, "operator_label": r.operator_label,
             "overrides": len(r.overrides)}
            for r in self.records.values()
            if r.organization_id == cur
            and (order_id is None or r.subject["order_id"] == order_id)
            and (unit_id is None or r.subject.get("unit_id") == unit_id)
            and (decision is None or r.outcome.decision.value == decision)
        ]

    def counts_by_decision(self, cur):
        return {}

    def save_record(self, cur, record, photos):
        self.records[record.record_id] = record
        for p in photos:
            self.images[p.image_id] = (record.organization_id, p.mime, p.jpeg)

    def update_record(self, cur, record):
        self.records[record.record_id] = record

    def get_record(self, cur, record_id):
        r = self.records.get(record_id)
        return r if r and r.organization_id == cur else None

    def get_image(self, cur, image_id):
        found = self.images.get(image_id)
        return (found[1], found[2]) if found and found[0] == cur else None


class FakeDb:
    @contextmanager
    def org(self, org_id):
        yield org_id

    @contextmanager
    def anonymous(self):
        yield None


@pytest.fixture
def client(monkeypatch, catalogue):
    import app.main as main

    fake = FakeStore()
    for name in ["resolve_code", "org_name", "list_orders", "get_order", "list_records", "counts_by_decision",
                 "save_record", "update_record", "get_record", "get_image"]:
        monkeypatch.setattr(main.store, name, getattr(fake, name))
    monkeypatch.setattr(main, "db", lambda: FakeDb())
    monkeypatch.setattr(main, "org_catalogue", lambda org: (catalogue, None))
    c = TestClient(main.app)
    c.fake = fake
    return c


def add_order(fake, *lines, order_id="ORD-1", org="org_demo_alpha"):
    order = make_order(*lines, order_id=order_id).model_copy(update={"organization_id": org})
    fake.orders[(org, order_id)] = order
    return order


def test_login_required_and_login_flow(client):
    assert client.get("/", follow_redirects=False).status_code == 303
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
    assert client.get(f"/images/{record.images[0].image_id}").status_code == 200
    for path in ["/", "/records", "/orders/ORD-1", f"/api/records/{record.record_id}"]:
        assert client.get(path).status_code == 200, path


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
