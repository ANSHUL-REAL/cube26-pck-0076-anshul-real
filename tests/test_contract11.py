"""The organisers' Evidence Contract 1.1: record shape, content hash, the four /v1 endpoints,
fail-open captures, and the read-only record link that needs no sign-in.

Web tests use the in-memory store from test_pages.py; no database and no model calls.
"""

import hashlib
import json

import jsonschema
import pytest
from conftest import ROOT
from test_pages import add_order, make_client

from pack_manager.contract import CHECK_KEYS, canonical, to_contract
from pack_manager.evidence import apply_override
from pack_manager.models import Decision, EvidenceRecord
from pack_manager.orders import parse_orders_csv
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.vision.oracle import OraclePerceiver

SCHEMA = json.loads((ROOT / "contract" / "evidence-contract-1.1.schema.json").read_text(encoding="utf-8"))
ALPHA = {"X-Access-Code": "alpha-demo"}
BRAVO = {"X-Access-Code": "bravo-demo"}


def example(name: str) -> EvidenceRecord:
    return EvidenceRecord.model_validate_json((ROOT / "contract/examples" / f"{name}.json").read_text("utf-8"))


def valid(record: dict) -> dict:
    jsonschema.validate(record, SCHEMA)
    return record


# ------------------------------------------------------------------ the record


@pytest.mark.parametrize("name", ["seal", "stop_and_fix", "uncertain", "pending", "overridden"])
def test_every_record_is_exactly_the_contract_shape(name):
    rec = valid(to_contract(example(name), image_bytes={}))
    assert rec["schema_version"] == "1.1" and rec["agent"] == "pack" and rec["subject"]["type"] == "order"
    # Every record carries the same check keys in the same order, so Recovery can match on them.
    assert [c["check_key"] for c in rec["checks"]] == CHECK_KEYS


def test_content_hash_is_the_contracts_definition():
    rec = to_contract(example("stop_and_fix"))
    text = "".join(i["sha256"] for i in rec["images"]) + canonical(rec["checks"])
    assert rec["content_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_verdicts_roll_up_and_the_box_decision_is_its_own_check():
    rec = {c["check_key"]: c for c in to_contract(example("stop_and_fix"))["checks"]}
    assert rec["all_items_present"]["verdict"] == "fail" and rec["order_matches_manifest"]["verdict"] == "fail"
    # Our per-product checks are kept under detail, the contract's extension point.
    assert any(s["check_key"].startswith("line_present:") for s in rec["all_items_present"]["detail"]["source_checks"])
    uncertain = {c["check_key"]: c["verdict"] for c in to_contract(example("uncertain"))["checks"]}
    assert uncertain["order_matches_manifest"] == "uncertain"  # never a low-confidence pass


def test_pending_record_says_pending_and_judges_nothing():
    rec = to_contract(example("pending"))
    assert rec["status"] == "pending" and rec["outcome"]["decision"] == "PENDING"
    model_checks = [c for c in rec["checks"] if c["check_key"] not in ("image_quality", "photo_reuse")]
    assert {c["verdict"] for c in model_checks} == {"uncertain"}
    assert all(c["detail"].get("not_checked") for c in model_checks[:-1])


def test_an_override_is_appended_and_leaves_the_checks_and_hash_alone():
    before = to_contract(example("uncertain"))
    after = to_contract(apply_override(example("uncertain"), Decision.SEAL, "hidden_item_verified", "op_alpha",
                                       note="lifted the top item"))
    assert after["checks"] == before["checks"] and after["content_hash"] == before["content_hash"]
    assert after["outcome"]["decided_by"] == "operator" and after["outcome"]["decision"] == "SEAL"
    (o,) = after["overrides"]
    assert (o["check_key"], o["from_verdict"], o["to_verdict"], o["by"]) == \
        ("order_matches_manifest", "uncertain", "pass", "op_alpha")
    assert o["reason"].startswith("hidden_item_verified") and "lifted the top item" in o["reason"]


def test_ids_are_uuids_and_stay_the_same():
    a, b = to_contract(example("seal")), to_contract(example("seal"))
    assert a["record_id"] == b["record_id"] and a["organization_id"] == b["organization_id"]


def test_shipment_id_goes_from_the_order_file_to_the_record(catalogue, settings, sharp_photo):
    text = "order_id,order_lines,shipment_id\nORD-9,CAP-BLU:1,SHP-5501\n"
    (order,) = parse_orders_csv(text, "org_test", catalogue).orders
    assert order.shipment_id == "SHP-5501"
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings, operator_label="op")
    rec = valid(to_contract(record, image_bytes={p.image_id: len(p.jpeg) for p in prepared}, catalogue=catalogue))
    assert rec["subject"]["shipment_id"] == "SHP-5501"
    assert rec["subject"]["sku"] == "CAP-BLU" and rec["subject"]["quantity_expected"] == 1
    assert rec["subject"]["quantity_observed"] == 1
    assert rec["images"][0]["bytes"] == len(prepared[0].jpeg)


# ------------------------------------------------------------------ the endpoints


@pytest.fixture
def client(monkeypatch, catalogue):
    return make_client(monkeypatch, catalogue)


def _box(client, settings, sharp_photo, seen, order_id="ORD-1", org="org_demo_alpha", at=None):
    order = add_order(client.fake, ("CAP-BLU", 1), order_id=order_id, org=org)
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(order, prepared, *_model(client, seen), settings, operator_label="op",
                        captured_at=at)
    client.fake.save_record(org, record, prepared)
    return record


def _model(client, seen):
    import app.main as main
    catalogue, _ = main.org_catalogue("org_demo_alpha")
    return catalogue, OraclePerceiver(seen)


def test_get_record_is_the_contract_record_and_other_companies_get_nothing(client, settings, sharp_photo):
    record = _box(client, settings, sharp_photo, {"CAP-BLU": 1})
    rid = to_contract(record)["record_id"]
    assert rid == record.record_id  # new records have UUID ids already
    assert client.get(f"/v1/records/{rid}").status_code == 401
    rec = valid(client.get(f"/v1/records/{rid}", headers=ALPHA).json())
    assert rec["outcome"]["decision"] == "SEAL" and rec["images"][0]["bytes"] > 0
    assert client.get(f"/v1/records/{rid}", headers=BRAVO).status_code == 404
    assert client.get("/v1/records", headers=BRAVO).json() == {"records": [], "next_cursor": None}


def test_record_list_pages_with_a_cursor_and_filters(client, settings, sharp_photo):
    from datetime import datetime, timezone
    times = [datetime(2026, 9, 30, 10, m, tzinfo=timezone.utc) for m in (1, 2, 3)]
    ids = [_box(client, settings, sharp_photo, {"CAP-BLU": 1}, order_id=f"ORD-{i}", at=t).record_id
           for i, t in enumerate(times)]
    first = client.get("/v1/records?limit=2", headers=ALPHA).json()
    assert [r["record_id"] for r in first["records"]] == ids[:2] and first["next_cursor"]
    second = client.get(f"/v1/records?limit=2&cursor={first['next_cursor']}", headers=ALPHA).json()
    assert [r["record_id"] for r in second["records"]] == ids[2:] and second["next_cursor"] is None
    since = client.get("/v1/records?since=2026-09-30T10:02:00Z", headers=ALPHA).json()
    assert [r["record_id"] for r in since["records"]] == ids[1:]
    assert client.get("/v1/records?agent=prep", headers=ALPHA).json()["records"] == []
    assert len(client.get("/v1/records?agent=pack", headers=ALPHA).json()["records"]) == 3
    assert client.get("/v1/records?cursor=nonsense", headers=ALPHA).status_code == 400


def _capture(client, sharp_photo, headers=ALPHA, shots=2):
    start = client.post("/v1/captures", json={"order_id": "ORD-1", "shots": shots}, headers=headers).json()
    for url in start["upload_urls"]:
        assert client.put(url, content=sharp_photo).json()["ok"]
    return start


def test_capture_upload_and_complete_fails_open_to_a_pending_record(client, sharp_photo):
    add_order(client.fake, ("CAP-BLU", 1))
    start = _capture(client, sharp_photo)
    assert len(start["upload_urls"]) == 2 and len(start["shots"]) == 2
    # Tests have no model key: the check can't run, and the record is saved anyway.
    done = client.post(f"/v1/captures/{start['capture_id']}/complete", headers=ALPHA).json()
    assert done["status"] == "pending" and done["decision"] == "PENDING"
    rec = valid(client.get(f"/v1/records/{done['record_id']}", headers=ALPHA).json())
    assert rec["status"] == "pending" and len(rec["images"]) == 2
    # Completing again (a retry after a dropped connection) returns the same record.
    again = client.post(f"/v1/captures/{start['capture_id']}/complete", headers=ALPHA).json()
    assert again == done and len(client.fake.records) == 1


def test_capture_upload_urls_only_work_for_their_own_capture(client, sharp_photo):
    add_order(client.fake, ("CAP-BLU", 1))
    start = client.post("/v1/captures", json={"order_id": "ORD-1"}, headers=ALPHA).json()
    url = start["upload_urls"][0]
    assert client.put(url.replace("token=", "token=x"), content=sharp_photo).status_code == 404
    assert client.put(url.replace("/photos/1", "/photos/3"), content=sharp_photo).status_code == 404
    assert client.put(url, content=b"").status_code == 400
    assert client.put(url, content=sharp_photo).status_code == 200
    assert client.put(url, content=sharp_photo).status_code == 200  # a retried upload replaces the photo
    # Another company can't complete it, and nothing can be completed without photos.
    assert client.post(f"/v1/captures/{start['capture_id']}/complete", headers=BRAVO).status_code == 404
    empty = client.post("/v1/captures", json={"order_id": "ORD-1"}, headers=ALPHA).json()
    assert client.post(f"/v1/captures/{empty['capture_id']}/complete", headers=ALPHA).status_code == 400
    assert client.post("/v1/captures", json={"order_id": "NOPE"}, headers=ALPHA).status_code == 404
    assert client.post("/v1/captures", json={"order_id": "ORD-1"}).status_code == 401


# ------------------------------------------------------------------ the read-only record link


def _share(client, record) -> str:
    client.post("/login", data={"code": "alpha-demo"})
    html = client.get(f"/records/{record.record_id}").text
    link = html.split('data-copy-link="')[1].split('"')[0]
    client.post("/logout")
    return link


def test_share_link_shows_the_record_without_sign_in_and_nothing_else(client, settings, sharp_photo):
    record = _box(client, settings, sharp_photo, {"CAP-BLU": 1})
    other = _box(client, settings, sharp_photo, {"CAP-BLU": 1}, order_id="ORD-2")
    link = _share(client, record)
    assert link.startswith("/r/")
    page = client.get(link)
    assert page.status_code == 200 and "Seal the box" in page.text and record.content_hash in page.text
    assert 'name="decision"' not in page.text and "Record your decision" not in page.text  # read-only
    assert client.get(f"{link}/images/{record.images[0].image_id}").status_code == 200
    assert client.get(f"{link}/images/{other.images[0].image_id}").status_code == 404  # not this record's
    assert client.get(f"/images/{record.images[0].image_id}", follow_redirects=False).status_code == 303
    valid(client.get(f"{link}/contract.json").json())
    assert json.loads(client.get(f"{link}/record.json").content)["record_id"] == record.record_id
    # A changed or made-up link opens nothing.
    assert client.get(link[:-2] + "xx").status_code == 404
    assert client.get("/r/abc").status_code == 404


def test_published_contract_examples_are_valid_and_current():
    from pack_manager.catalogue import load_catalogue
    catalogues = [load_catalogue(ROOT / "catalogue" / d) for d in ("org_bench_abid", "sample")]
    for name in ["seal", "stop_and_fix", "uncertain", "pending", "overridden"]:
        published = valid(json.loads((ROOT / "contract/examples-1.1" / f"{name}.json").read_text("utf-8")))
        record = example(name)
        skus = [line["sku"] for line in record.subject["expected_lines"]]
        catalogue = next((c for c in catalogues if all(c.get(s) for s in skus)), None)
        fresh = to_contract(record, image_bytes={i["key"]: i["bytes"] for i in published["images"]},
                            catalogue=catalogue)
        assert fresh == published, "run: python contract/build_contract.py"
        assert all(i["bytes"] > 0 for i in published["images"])


# ------------------------------------------------------------------ one override per check


def test_a_person_can_override_any_check_with_a_reason(client, settings, sharp_photo):
    import re
    record = _box(client, settings, sharp_photo, {"CAP-BLU": 1})
    rid = record.record_id
    client.post("/login", data={"code": "alpha-demo"})
    page = client.get(f"/records/{rid}").text
    assert page.count('action="/records/' + rid + '/check"') == 6  # every check but the box decision
    prior = re.search(r'name="prior_hash" value="([^"]*)"', page).group(1)
    before = client.get(f"/v1/records/{rid}", headers=ALPHA).json()

    form = {"check_key": "quantities_correct", "to_verdict": "fail", "reason_code": "agent_miscount",
            "note": "counted two", "prior_hash": prior}
    for missing, message in [("reason_code", "Choose a reason"), ("to_verdict", "Choose the result")]:
        r = client.post(f"/records/{rid}/check", data={**form, missing: ""})
        assert r.status_code == 400 and message in r.text
    r = client.post(f"/records/{rid}/check", data={**form, "check_key": "order_matches_manifest"})
    assert r.status_code == 400
    assert client.post(f"/records/{rid}/check", data=form, follow_redirects=False).status_code == 303

    saved = client.fake.records[rid]
    assert saved.outcome.decision == Decision.SEAL and saved.status == record.status  # box unchanged
    assert saved.checks == record.checks and saved.box_overrides == []
    after = valid(client.get(f"/v1/records/{rid}", headers=ALPHA).json())
    assert after["checks"] == before["checks"] and after["content_hash"] == before["content_hash"]
    assert after["outcome"]["decided_by"] == "agent"
    (o,) = after["overrides"]
    assert (o["check_key"], o["from_verdict"], o["to_verdict"], o["by"]) == ("quantities_correct", "pass", "fail", "op_alpha")
    assert "counted two" in o["reason"]
    html = client.get(f"/records/{rid}").text
    assert "changed quantities right: pass to fail" in html and "Changed by op_alpha" in html
    # The same result again is refused; a stale form is a conflict.
    again = client.post(f"/records/{rid}/check", data={**form, "prior_hash": saved.content_hash})
    assert again.status_code == 400 and "already has that result" in again.text
    assert client.post(f"/records/{rid}/check", data=form).status_code == 409
    from pack_manager.evidence import verify_history
    assert verify_history(saved) is True


def test_the_share_link_page_has_no_override_forms(client, settings, sharp_photo):
    record = _box(client, settings, sharp_photo, {"CAP-BLU": 1})
    html = client.get(_share(client, record)).text
    assert "/check" not in html and "Override</summary>" not in html and "All items present" in html
