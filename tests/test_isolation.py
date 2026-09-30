"""Tenant isolation, tested against a real Postgres (engineering rule 1).

Needs TEST_DATABASE_URL / TEST_DATABASE_ADMIN_URL, or else DATABASE_URL (the pack_app role) and
DATABASE_ADMIN_URL, in the environment or .env, e.g. `docker compose up -d db && python -m app.migrate`.
Skipped otherwise. The tests only add orders named ISO-..., and delete them again before and after,
so running them against the demo database leaves it as it was.
"""

import os
import uuid

import psycopg2
import pytest
from conftest import make_order

from pack_manager.config import Settings
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.vision.oracle import OraclePerceiver

S = Settings()
APP_URL = os.environ.get("TEST_DATABASE_URL") or S.database_url
ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL") or S.database_admin_url
# In CI (REQUIRE_DB=1) a missing or unreachable database is a failure, not a skip.
REQUIRE_DB = bool(os.environ.get("REQUIRE_DB"))
pytestmark = pytest.mark.skipif(
    not REQUIRE_DB and not (APP_URL and ADMIN_URL),
    reason="DATABASE_URL / DATABASE_ADMIN_URL not set",
)

ALPHA, BRAVO = "org_demo_alpha", "org_demo_bravo"
TENANT_TABLES = ["organizations", "orders", "records", "images"]


def _remove_test_rows() -> None:
    """Delete what these tests add (orders named ISO-...). RLS is forced even for the owner,
    so each organisation's rows are deleted with that organisation set."""
    conn = psycopg2.connect(ADMIN_URL)
    with conn, conn.cursor() as cur:
        for org in (ALPHA, BRAVO):
            cur.execute("select set_config('app.org_id', %s, true)", (org,))
            test_ids = ("ISO-%",)
            cur.execute("delete from images where record_id in "
                        "(select record_id from records where order_id like %s)", test_ids)
            cur.execute("delete from records where order_id like %s", test_ids)
            cur.execute("delete from orders where order_id like %s", test_ids)
    conn.close()


@pytest.fixture(scope="module")
def database():
    from app.db import Database
    from app.migrate import migrate, seed

    try:
        migrate(ADMIN_URL, S.pack_app_db_password)
        seed(ADMIN_URL, sample_orders=False)  # organisations and demo codes only
        _remove_test_rows()
        d = Database(APP_URL)
    except psycopg2.OperationalError as exc:
        if REQUIRE_DB:
            raise
        pytest.skip(f"database not reachable: {exc}")
    yield d
    d.close()
    _remove_test_rows()


@pytest.fixture(scope="module")
def alpha_record(database, sharp_photo_module, catalogue_module, settings_module):
    from app import store

    prepared = prepare_photos([Photo(sharp_photo_module)], settings_module)
    order = make_order(("CAP-BLU", 1), order_id=f"ISO-{uuid.uuid4().hex[:8]}")
    order = order.model_copy(update={"organization_id": ALPHA})
    record = verify_box(order, prepared, catalogue_module, OraclePerceiver({"CAP-BLU": 1}), settings_module,
                        operator_label="op_alpha")
    with database.org(ALPHA) as cur:
        store.upsert_order(cur, order)
        store.save_record(cur, record, prepared)
    return record


@pytest.fixture(scope="module")
def sharp_photo_module():
    import numpy as np
    from conftest import jpeg_bytes

    yy, xx = np.mgrid[0:900, 0:1200]
    board = (((yy // 30) + (xx // 30)) % 2 * 160 + 40).astype("uint8")
    return jpeg_bytes(np.stack([board] * 3, axis=-1))


@pytest.fixture(scope="module")
def catalogue_module():
    from pack_manager.models import Catalogue, CatalogueItem

    return Catalogue(items=[CatalogueItem(sku="CAP-BLU", title="Blue Cap")])


@pytest.fixture(scope="module")
def settings_module():
    return Settings(_env_file=None)


def test_app_role_cannot_bypass_rls(database):
    with database.anonymous() as cur:
        cur.execute("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
        role = cur.fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}
        cur.execute(
            "select relname, relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner) as owner "
            "from pg_class where relname = any(%s)", (TENANT_TABLES,),
        )
        rows = cur.fetchall()
        assert len(rows) == len(TENANT_TABLES)
        for r in rows:
            assert r["relrowsecurity"] and r["relforcerowsecurity"], r["relname"]
            assert r["owner"] != "pack_app", r["relname"]


def test_other_org_sees_zero_rows(database, alpha_record):
    from app import store

    with database.org(ALPHA) as cur:
        assert store.get_record(cur, alpha_record.record_id) is not None
    with database.org(BRAVO) as cur:
        assert store.get_record(cur, alpha_record.record_id) is None
        cur.execute("select count(*) as n from records where organization_id = %s", (ALPHA,))
        assert cur.fetchone()["n"] == 0
        cur.execute("select count(*) as n from orders where organization_id = %s", (ALPHA,))
        assert cur.fetchone()["n"] == 0


def test_guessing_an_image_id_returns_nothing(database, alpha_record):
    from app import store

    image_id = alpha_record.images[0].image_id
    sha = alpha_record.images[0].sha256
    with database.org(ALPHA) as cur:
        assert store.get_image(cur, image_id) is not None
        assert store.find_image_uses(cur, [sha])
    with database.org(BRAVO) as cur:
        assert store.get_image(cur, image_id) is None
        assert store.find_image_uses(cur, [sha]) == []  # the reuse check can't reveal other orgs' photos


def test_no_tenant_set_means_no_rows(database, alpha_record):
    with database.anonymous() as cur:
        for table in TENANT_TABLES:
            cur.execute(f"select count(*) as n from {table}")
            assert cur.fetchone()["n"] == 0, table


def test_cannot_write_into_another_org(database):
    from app import store

    order = make_order(("CAP-BLU", 1), order_id=f"ISO-{uuid.uuid4().hex[:8]}")
    order = order.model_copy(update={"organization_id": ALPHA})
    with pytest.raises(psycopg2.Error):
        with database.org(BRAVO) as cur:
            store.upsert_order(cur, order)


def test_access_codes_are_not_readable_but_resolve(database):
    from app import store

    with database.anonymous() as cur:
        assert store.resolve_code(cur, "bravo-demo")["organization_id"] == BRAVO
        assert store.resolve_code(cur, "nope") is None
    with pytest.raises(psycopg2.Error):
        with database.anonymous() as cur:
            cur.execute("select * from access_codes")


def test_http_bravo_gets_404_for_alpha_record_and_photo(database, alpha_record):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    client.post("/login", data={"code": "bravo-demo"})
    assert client.get(f"/records/{alpha_record.record_id}").status_code == 404
    assert client.get(f"/images/{alpha_record.images[0].image_id}").status_code == 404
    assert client.get(f"/api/records/{alpha_record.record_id}").status_code == 404

    client.post("/login", data={"code": "alpha-demo"})
    assert client.get(f"/records/{alpha_record.record_id}").status_code == 200
    assert client.get(f"/images/{alpha_record.images[0].image_id}").status_code == 200


def test_records_are_append_only(database, alpha_record):
    """The database itself keeps evidence append-only: a hand decision can be added, but the
    agent's part of a record and earlier decisions can't be rewritten, even by the app role."""
    import json

    from app import store
    from pack_manager.evidence import apply_override
    from pack_manager.models import Decision

    with database.org(ALPHA) as cur:
        current = store.get_record(cur, alpha_record.record_id)
        decided = apply_override(current, Decision.STOP_AND_FIX, "other", "op_alpha", note="append-only test")
        assert store.update_record(cur, decided, prior_hash=current.content_hash)

    def rewrite(change):
        data = json.loads(decided.model_dump_json())
        change(data)
        with database.org(ALPHA) as cur:
            cur.execute("update records set record = %s where record_id = %s",
                        (json.dumps(data), decided.record_id))

    def drop_a_check(d):
        d["checks"] = d["checks"][:-1]

    def reword_the_decision(d):
        d["overrides"][0]["note"] = "edited later"
        d["overrides"].append(d["overrides"][0])

    def undo_the_decision(d):
        d["overrides"] = []

    for change in (drop_a_check, reword_the_decision, undo_the_decision):
        with pytest.raises(psycopg2.Error, match="append-only"):
            rewrite(change)
    with database.org(ALPHA) as cur:
        assert store.get_record(cur, alpha_record.record_id) == decided  # nothing was changed
