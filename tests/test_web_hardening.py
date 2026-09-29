"""Web app edge cases: forms without JavaScript, stale decisions, big uploads, odd order ids,
friendly error pages, cross-site posts, retried records, the session key and the connection pool.

Uses the in-memory store from test_pages.py; no database and no model calls.
"""

import csv
import re
import threading
import time
import uuid
from contextlib import ExitStack

import psycopg2
import pytest
from fastapi.testclient import TestClient
from test_pages import _pending_box, add_order, make_client

from pack_manager.models import Decision
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.vision.oracle import OraclePerceiver


@pytest.fixture
def client(monkeypatch, catalogue):
    return make_client(monkeypatch, catalogue)


def _login(client):
    client.post("/login", data={"code": "alpha-demo"})


def _form(html: str, name: str) -> str:
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


def _decide(client, rid, **data):
    page = client.get(f"/records/{rid}").text
    form = {"reason_code": "agent_unavailable", "note": "", "prior_hash": _form(page, "prior_hash"), **data}
    return client.post(f"/records/{rid}/decision", data=form, follow_redirects=False)


# ------------------------------------------------------------------ the decision form


def test_decision_comes_from_the_button_so_it_works_without_javascript(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    html = client.get(f"/records/{rid}").text
    # Each button carries its decision; nothing waits for a script to fill a hidden field.
    assert '<button class="btn seal lg" type="submit" name="decision" value="SEAL">' in html
    assert 'name="decision" value="STOP_AND_FIX"' in html
    assert '<input type="hidden" name="decision"' not in html
    # The note is a textarea, so Enter adds a line instead of submitting the first button (Seal).
    assert re.search(r'<textarea id="note" name="note" rows="2"', html)
    assert not re.search(r'<input[^>]*name="note"', html)
    assert _form(html, "prior_hash") == client.fake.records[rid].content_hash

    resp = _decide(client, rid, decision="STOP_AND_FIX", note="line one\nline two")
    assert resp.status_code == 303
    rec = client.fake.records[rid]
    assert rec.outcome.decision == Decision.STOP_AND_FIX and rec.overrides[0].note == "line one\nline two"


@pytest.mark.parametrize("data,message", [
    ({"decision": ""}, "Choose Seal the box or Stop and fix"),
    ({"decision": "UNCERTAIN"}, "Choose Seal the box or Stop and fix"),
    ({"decision": "SEAL", "reason_code": ""}, "Choose a reason for your decision."),
    ({"decision": "SEAL", "reason_code": "made-up"}, "Choose a reason for your decision."),
])
def test_invalid_decision_shows_an_error_and_saves_nothing(client, sharp_photo, data, message):
    rid = _pending_box(client, sharp_photo)
    before = client.fake.records[rid]
    resp = _decide(client, rid, note="kept for the next try", **data)
    assert resp.status_code == 400 and message in resp.text
    assert "kept for the next try" in resp.text  # the note isn't lost
    assert client.fake.records[rid] == before


def test_missing_fields_are_not_a_json_error(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    resp = client.post(f"/records/{rid}/decision", data={"decision": "SEAL"})
    assert resp.status_code == 400 and resp.headers["content-type"].startswith("text/html")
    assert "Choose a reason for your decision." in resp.text


def test_stale_decision_is_refused_with_a_conflict_message(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    seen = _form(client.get(f"/records/{rid}").text, "prior_hash")
    # Someone else decides first.
    assert _decide(client, rid, decision="SEAL").status_code == 303
    after_first = client.fake.records[rid]

    resp = client.post(f"/records/{rid}/decision", data={
        "decision": "STOP_AND_FIX", "reason_code": "agent_miscount", "note": "", "prior_hash": seen})
    assert resp.status_code == 409
    assert "This record changed while you were deciding." in resp.text and "Reload and check it again." in resp.text
    assert client.fake.records[rid] == after_first  # the first decision is kept, not overwritten


def test_concurrent_write_is_detected_by_the_store(client, sharp_photo, monkeypatch):
    import app.main as main

    rid = _pending_box(client, sharp_photo)
    monkeypatch.setattr(main.store, "update_record", lambda cur, record, prior_hash: False)  # lost the race
    resp = _decide(client, rid, decision="SEAL")
    assert resp.status_code == 409 and "This record changed while you were deciding." in resp.text


def test_a_record_that_fails_its_hash_cannot_be_decided(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    edited = client.fake.records[rid].model_copy(update={"operator_label": "someone else"})  # hash not updated
    client.fake.records[rid] = edited
    resp = _decide(client, rid, decision="SEAL")
    assert resp.status_code == 409 and "doesn&#39;t match its content hash" in resp.text
    assert client.fake.records[rid] == edited


def test_override_chain_status_is_shown(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    assert "Every earlier version checks out" not in client.get(f"/records/{rid}").text  # no overrides yet
    _decide(client, rid, decision="SEAL")
    assert "Every earlier version checks out" in client.get(f"/records/{rid}").text


# ------------------------------------------------------------------ uploads


def test_more_photos_than_allowed_keeps_the_first_ones(client, sharp_photo):
    import app.main as main

    add_order(client.fake, ("CAP-BLU", 1))
    _login(client)
    files = [("photos", (f"p{i}.jpg", sharp_photo, "image/jpeg")) for i in range(main.settings.max_box_photos + 1)]
    resp = client.post("/orders/ORD-1/verify", files=files, follow_redirects=False)
    assert resp.status_code == 303
    rec = client.fake.records[resp.headers["location"].rsplit("/", 1)[1]]
    assert len(rec.images) == main.settings.max_box_photos


def test_oversized_photo_is_refused_nicely(client, sharp_photo):
    import app.main as main

    add_order(client.fake, ("CAP-BLU", 1))
    _login(client)
    big = sharp_photo + b"\0" * main.MAX_PHOTO_BYTES
    resp = client.post("/orders/ORD-1/verify", files={"photos": ("big.jpg", big, "image/jpeg")})
    assert resp.status_code == 200 and "Photo 1 is larger than 15 MB" in resp.text
    assert not client.fake.records


def test_unreadable_photos_get_a_message_not_a_server_error(client, monkeypatch):
    import app.main as main

    add_order(client.fake, ("CAP-BLU", 1))
    _login(client)
    resp = client.post("/orders/ORD-1/verify", files={"photos": ("x.jpg", b"not an image", "image/jpeg")})
    assert resp.status_code == 200 and 'class="callout error"' in resp.text

    def broken(*args, **kwargs):  # e.g. a decoder error that isn't a ValueError
        raise SyntaxError("broken PNG file")

    monkeypatch.setattr(main, "prepare_photos", broken)
    resp = client.post("/orders/ORD-1/verify", files={"photos": ("x.png", b"\x89PNG....", "image/png")})
    assert resp.status_code == 200 and main.PHOTO_UNREADABLE.replace("'", "&#39;") in resp.text
    assert not client.fake.records


def test_a_check_that_cannot_run_shows_its_reason(client, sharp_photo, monkeypatch):
    import app.main as main

    def no_lines(*args, **kwargs):
        raise ValueError("The order has no lines to check the box against.")

    monkeypatch.setattr(main, "verify_box", no_lines)
    add_order(client.fake, ("CAP-BLU", 1))
    _login(client)
    resp = client.post("/orders/ORD-1/verify", files={"photos": ("b.jpg", sharp_photo, "image/jpeg")})
    assert resp.status_code == 200 and "The order has no lines to check the box against." in resp.text


def test_quality_stash_is_capped_and_expires(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "_STASH", {})
    keys = [main._stash_put("org", "ORD-1", []) for _ in range(main.STASH_MAX + 10)]
    assert len(main._STASH) == main.STASH_MAX
    assert main._stash_take(keys[0], "org", "ORD-1") is None  # the oldest were dropped
    assert main._stash_take(keys[-1], "org", "ORD-1") == []
    old = main._stash_put("org", "ORD-1", [])
    org, order_id, photos, at = main._STASH[old]
    main._STASH[old] = (org, order_id, photos, at - main.STASH_TTL_S - 1)
    assert main._stash_take(old, "org", "ORD-1") is None  # expired, even if not yet swept


# ------------------------------------------------------------------ CSV import


def test_csv_over_2_mb_is_refused_not_cut_short(client):
    _login(client)
    header = b"order_id,order_lines,channel\n"
    data = header + b"ORD-1,CAP-BLU:12," + b"x" * (2_000_001 - len(header) - 18) + b"\n"
    assert len(data) == 2_000_001
    resp = client.post("/orders/import", files={"file": ("orders.csv", data, "text/csv")})
    assert "larger than 2 MB" in resp.text
    assert not client.fake.orders


@pytest.mark.parametrize("error", [ValueError("bad row"), csv.Error("field larger than field limit")])
def test_csv_that_cannot_be_parsed_gets_a_message(client, monkeypatch, error):
    import app.main as main

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(main, "parse_orders_csv", broken)
    _login(client)
    resp = client.post("/orders/import", files={"file": ("o.csv", b"order_id,order_lines\nA,B:1\n", "text/csv")})
    assert resp.status_code == 400 and "couldn&#39;t be read as a list of orders" in resp.text


def test_import_without_a_file(client):
    _login(client)
    resp = client.post("/orders/import", data={})
    assert resp.status_code == 400 and "Choose a CSV file first." in resp.text


# ------------------------------------------------------------------ order ids in links


def test_order_ids_with_url_characters_open_and_check(client, sharp_photo):
    odd = "A/B #1?x%"
    add_order(client.fake, ("CAP-BLU", 1), order_id=odd)
    _login(client)
    href = "/orders/A%2FB%20%231%3Fx%25"
    assert f'href="{href}"' in client.get("/?view=all").text
    page = client.get(href)
    assert page.status_code == 200 and "Photograph the open box" in page.text
    assert f'action="{href}/verify"' in page.text
    resp = client.post(f"{href}/verify", files={"photos": ("b.jpg", sharp_photo, "image/jpeg")},
                       follow_redirects=False)
    assert resp.status_code == 303
    record_page = client.get(resp.headers["location"]).text
    assert f'class="back" href="{href}"' in record_page
    # The "photo could be clearer" page lives at .../verify; opening that address again shows the order.
    again = client.get(f"{href}/verify", follow_redirects=False)
    assert again.status_code == 303 and again.headers["location"] == href


# ------------------------------------------------------------------ error pages


def test_unknown_pages_are_friendly_html_and_api_stays_json(client):
    _login(client)
    resp = client.get("/no/such/page")
    assert resp.status_code == 404 and resp.headers["content-type"].startswith("text/html")
    assert "Not found" in resp.text
    resp = client.delete("/records")
    assert resp.status_code == 405 and "Not found" in resp.text
    resp = client.get("/api/nothing-here")
    assert resp.status_code == 404 and resp.headers["content-type"] == "application/json"
    resp = client.post("/api/records")
    assert resp.status_code == 405 and resp.headers["content-type"] == "application/json"
    assert client.get("/api/records", params={"since": "not-a-date"}).status_code == 422


def test_bad_form_data_is_a_friendly_page(client):
    add_order(client.fake, ("CAP-BLU", 1))
    _login(client)
    resp = client.post("/orders/ORD-1/verify", data={"photos": "not a file"})
    assert resp.status_code == 400 and resp.headers["content-type"].startswith("text/html")
    assert "Go back and try again." in resp.text


def test_server_errors_are_a_plain_page(client, monkeypatch):
    import app.main as main

    def boom(*args, **kwargs):
        raise RuntimeError("something broke")

    def asleep(*args, **kwargs):
        raise psycopg2.OperationalError("could not connect to server")

    quiet = TestClient(main.app, raise_server_exceptions=False)
    quiet.post("/login", data={"code": "alpha-demo"})
    monkeypatch.setattr(main.store, "list_records", boom)
    resp = quiet.get("/records")
    assert resp.status_code == 500 and "Something went wrong on our side." in resp.text
    assert "something broke" not in resp.text  # no internals on the page
    api = quiet.get("/api/records")
    assert api.status_code == 500 and "Something went wrong on our side." in api.json()["error"]
    monkeypatch.setattr(main.store, "list_records", asleep)
    resp = quiet.get("/records")
    assert resp.status_code == 503 and "The database isn&#39;t answering" in resp.text


def test_image_ids_in_other_forms_are_not_found(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    image_id = client.fake.records[rid].images[0].image_id
    assert client.get(f"/images/urn:uuid:{uuid.uuid4()}").status_code == 404
    assert client.get("/images/not-a-uuid").status_code == 404
    assert client.get(f"/images/urn:uuid:{image_id}").status_code == 200  # the same id, written differently
    assert client.get(f"/images/{image_id}").status_code == 200


# ------------------------------------------------------------------ cross-site posts and sign out


def test_post_from_another_site_is_refused(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    resp = client.post(f"/records/{rid}/decision", headers={"Origin": "https://evil.example"},
                       data={"decision": "SEAL", "reason_code": "agent_unavailable"})
    assert resp.status_code == 403 and "sent from another website" in resp.text
    assert not client.fake.records[rid].overrides
    assert client.post("/login", headers={"Origin": "null"}, data={"code": "alpha-demo"}).status_code == 403


def test_same_origin_and_originless_posts_pass(client, sharp_photo):
    rid = _pending_box(client, sharp_photo)
    page = client.get(f"/records/{rid}").text
    resp = client.post(f"/records/{rid}/decision", headers={"Origin": "http://testserver"}, follow_redirects=False,
                       data={"decision": "SEAL", "reason_code": "agent_unavailable",
                             "prior_hash": _form(page, "prior_hash")})
    assert resp.status_code == 303 and client.fake.records[rid].overrides
    assert client.post("/login", data={"code": "alpha-demo"}, follow_redirects=False).status_code == 303


def test_sign_out_is_a_post_form(client):
    _login(client)
    assert '<form method="post" action="/logout"' in client.get("/").text
    assert client.post("/logout", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).status_code == 303  # signed out


# ------------------------------------------------------------------ retried records


def test_a_retried_pending_record_leaves_the_queue(client, sharp_photo, monkeypatch):
    import app.main as main

    rid = _pending_box(client, sharp_photo)
    assert rid in client.get("/records?decision=PENDING").text
    monkeypatch.setattr(main, "perceiver_for", lambda org: OraclePerceiver({"CAP-BLU": 1}))
    new = client.post(f"/records/{rid}/retry", follow_redirects=False).headers["location"].rsplit("/", 1)[1]

    old_page = client.get(f"/records/{rid}").text
    assert "Retry AI check" not in old_page and "Record your decision" not in old_page
    assert "Disagree with this result?" not in old_page
    assert f'href="/records/{new}"' in old_page and "The AI checked these photos again" in old_page
    assert rid not in client.get("/records?decision=PENDING").text
    assert client.fake.counts_by_decision("org_demo_alpha").get("PENDING", 0) == 0
    assert "Checked again" in client.get("/records").text  # still listed, with its own label

    count = len(client.fake.records)  # a second retry goes to the first one's result
    again = client.post(f"/records/{rid}/retry", follow_redirects=False)
    assert again.headers["location"] == f"/records/{new}" and len(client.fake.records) == count
    resp = client.post(f"/records/{rid}/decision", data={"decision": "SEAL", "reason_code": "agent_unavailable"})
    assert resp.status_code == 409 and not client.fake.records[rid].overrides


def test_retry_with_photos_that_fail_their_hash_is_a_message(client, sharp_photo, monkeypatch):
    import app.main as main

    rid = _pending_box(client, sharp_photo)
    key = next(iter(client.fake.images))
    org, mime, jpeg, sha, record_id = client.fake.images[key]
    client.fake.images[key] = (org, mime, jpeg + b"x", sha, record_id)
    monkeypatch.setattr(main, "perceiver_for", lambda org: OraclePerceiver({"CAP-BLU": 1}))
    resp = client.post(f"/records/{rid}/retry")
    assert resp.status_code == 409 and "saved photos don&#39;t match this record" in resp.text


# ------------------------------------------------------------------ orders tabs and the daily limit


def test_orders_waiting_for_a_person_stay_in_to_check(client, sharp_photo, catalogue, settings, monkeypatch):
    import app.main as main

    rid = _pending_box(client, sharp_photo, order_id="ORD-PEND")
    order = add_order(client.fake, ("CAP-BLU", 1), order_id="ORD-SEAL")
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    client.fake.save_record(None, verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings,
                                             operator_label="op_alpha"), prepared)
    todo, done = client.get("/?view=todo").text, client.get("/?view=done").text
    assert "ORD-PEND" in todo and "ORD-PEND" not in done
    assert f'href="/records/{rid}"' in todo  # opens the record, where the decision is made
    assert "ORD-SEAL" in done and "ORD-SEAL" not in todo

    for i in range(3):
        add_order(client.fake, ("CAP-BLU", 1), order_id=f"ORD-NEW-{i}")
    monkeypatch.setattr(main, "ORDERS_SHOWN", 2)
    html = client.get("/?view=todo").text
    assert "Showing the newest 2 of 4." in html
    assert re.search(r'To check <span class="count">4</span>', html)  # counts aren't capped by the list


def test_daily_limit_counts_only_boxes_the_model_answered(client, sharp_photo, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main.settings, "daily_checks_per_org", 2)
    add_order(client.fake, ("CAP-BLU", 1))
    _login(client)
    upload = {"photos": ("box.jpg", sharp_photo, "image/jpeg")}
    for _ in range(2):  # no model: two pending boxes, no AI checks used
        client.post("/orders/ORD-1/verify", files=upload)
    monkeypatch.setattr(main, "perceiver", lambda: OraclePerceiver({"CAP-BLU": 1}))
    url = client.post("/orders/ORD-1/verify", files=upload, follow_redirects=False).headers["location"]
    assert client.fake.records[url.rsplit("/", 1)[1]].outcome.decision == Decision.SEAL

    cached = client.fake.records[url.rsplit("/", 1)[1]]
    cached.observations["cached_response"] = True  # answers from the local cache don't count either
    assert client.fake.count_ai_checks_since("org_demo_alpha", cached.captured_at) == 0


# ------------------------------------------------------------------ session key


def test_default_or_short_session_secret_is_replaced():
    import app.main as main

    long_secret = "x" * 40
    assert main.session_secret(long_secret) == long_secret
    for weak in ("change-me", "short", "", None):
        key = main.session_secret(weak)
        assert key != weak and len(key) >= 32
    assert main.session_secret("change-me") != main.session_secret("change-me")


def test_session_cookie_secure_flag_follows_the_setting():
    import app.main as main
    from starlette.middleware.sessions import SessionMiddleware

    session = next(m for m in main.app.user_middleware if m.cls is SessionMiddleware)
    assert session.kwargs["https_only"] is main.settings.secure_cookies
    assert type(main.get_settings()).model_fields["secure_cookies"].default is False  # local HTTP keeps working


def test_cookie_signed_with_the_default_secret_is_not_a_sign_in(client):
    import base64
    import json

    from itsdangerous import TimestampSigner

    add_order(client.fake, ("CAP-BLU", 1), order_id="BRAVO-ORDER", org="org_demo_bravo")
    payload = base64.b64encode(json.dumps({"user": {"org": "org_demo_bravo", "org_name": "x", "operator": "x"}}).encode())
    client.cookies.set("session", TimestampSigner("change-me").sign(payload).decode())
    resp = client.get("/?view=all", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/login"


# ------------------------------------------------------------------ connection pool (app/db.py)


class _Conn:
    def __init__(self, dead=False):
        self.closed, self.dead, self.sql = 0, dead, []

    def cursor(self, cursor_factory=None):
        return _Cursor(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        if self.conn.dead:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        self.conn.sql.append(sql)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Pool:
    """Hands out the idle connections first, like psycopg2's pool, then new ones."""

    def __init__(self, idle):
        self.idle, self.discarded = list(idle), []

    def getconn(self):
        return self.idle.pop(0) if self.idle else _Conn()

    def putconn(self, conn, close=False):
        if close:
            conn.closed = 1
            self.discarded.append(conn)
        else:
            self.idle.append(conn)


def _database(pool, slots=8, wait_s=5.0):
    from app.db import Database

    database = Database.__new__(Database)
    database.pool, database._slots, database._wait_s = pool, threading.BoundedSemaphore(slots), wait_s
    return database


def test_a_dropped_connection_is_replaced_once():
    dead = _Conn(dead=True)
    database = _database(_Pool([dead]))
    with database.org("org_x") as cur:
        cur.execute("select 2")
    assert database.pool.discarded == [dead]
    fresh = database.pool.idle[0]
    assert fresh.sql[0].startswith("select set_config('app.org_id'") and fresh.sql[1] == "select 2"
    with database.anonymous() as cur:  # a sign-in transaction checks its connection too
        pass

    both_dead = _database(_Pool([_Conn(dead=True), _Conn(dead=True)]))
    both_dead.pool.getconn = lambda: _Conn(dead=True)
    with pytest.raises(psycopg2.OperationalError):
        with both_dead.org("org_x"):
            pass


def test_more_requests_than_connections_wait_instead_of_failing():
    from app.db import DatabaseBusy

    database = _database(_Pool([]), slots=2, wait_s=0.2)
    with ExitStack() as held:
        held.enter_context(database.org("a"))
        held.enter_context(database.org("b"))
        started = time.time()
        with pytest.raises(DatabaseBusy):
            with database.org("c"):
                pass
        assert time.time() - started >= 0.2  # it waited for a free connection first

    database._wait_s = 5.0
    done = []
    with ExitStack() as held:
        held.enter_context(database.org("a"))
        held.enter_context(database.org("b"))
        waiter = threading.Thread(target=lambda: done.append(database.org("c").__enter__()))
        waiter.start()
        time.sleep(0.1)
        assert not done
    waiter.join(2)
    assert done  # got a connection as soon as one was returned


def test_same_host_passes_behind_an_https_proxy(client):
    # Render ends HTTPS at its proxy: the browser says https, the app may see http.
    resp = client.post("/login", headers={"Origin": "https://testserver"}, data={"code": "alpha-demo"},
                       follow_redirects=False)
    assert resp.status_code == 303
