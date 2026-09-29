"""Create tables, row-level security policies and the pack_app role, then seed demo data.

    python -m app.migrate            # schema + role + seed
    python -m app.migrate --no-seed  # schema + role only
    python -m app.migrate --no-sample-orders  # live demo: only real orders (orders.json or CSV import)
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import psycopg2
from psycopg2 import sql

from pack_manager.config import get_settings
from pack_manager.models import Order, parse_lines

from .store import hash_code, upsert_order

ROOT = Path(__file__).resolve().parents[1]

ORGS = {
    "org_demo_alpha": "Alpha Outfitters (demo)",
    "org_demo_bravo": "Bravo Supplies (demo)",
}
DEMO_CODES = {
    "alpha-demo": ("org_demo_alpha", "op_alpha"),
    "bravo-demo": ("org_demo_bravo", "op_bravo"),
}


def migrate(admin_url: str, app_password: str) -> None:
    conn = psycopg2.connect(admin_url)
    with conn, conn.cursor() as cur:
        cur.execute((ROOT / "db" / "migrations" / "001_init.sql").read_text(encoding="utf-8"))
        cur.execute("select 1 from pg_roles where rolname = 'pack_app'")
        if cur.fetchone():
            cur.execute(sql.SQL("alter role pack_app with login password {}").format(sql.Literal(app_password)))
        else:
            cur.execute(sql.SQL("create role pack_app login password {}").format(sql.Literal(app_password)))
        cur.execute("grant usage on schema public to pack_app")
        cur.execute("grant select on organizations to pack_app")
        cur.execute("grant select, insert, update on orders to pack_app")
        cur.execute("grant select, insert, update on records to pack_app")
        cur.execute("grant select, insert on images to pack_app")
        cur.execute("revoke all on access_codes from pack_app")
        cur.execute("revoke all on function resolve_access_code(text) from public")
        cur.execute("grant execute on function resolve_access_code(text) to pack_app")
    conn.close()


def _as_org(cur, org_id: str) -> None:
    cur.execute("select set_config('app.org_id', %s, true)", (org_id,))


def seed(admin_url: str, sample_orders: bool = True) -> dict[str, int]:
    """Organisations, demo access codes, the organisers' sample orders, and any orders in
    catalogue/<org>/orders.json. Rows are written with app.org_id set, so the same
    policies that guard the app also check the seed."""
    counts: dict[str, int] = {}
    conn = psycopg2.connect(admin_url)
    with conn, conn.cursor() as cur:
        for org_id, name in ORGS.items():
            _as_org(cur, org_id)
            cur.execute(
                "insert into organizations (id, name) values (%s, %s) on conflict (id) do update set name = excluded.name",
                (org_id, name),
            )
        for code, (org_id, operator) in DEMO_CODES.items():
            cur.execute(
                """insert into access_codes (code_hash, organization_id, operator_label) values (%s, %s, %s)
                   on conflict (code_hash) do update set organization_id = excluded.organization_id,
                   operator_label = excluded.operator_label""",
                (hash_code(code), org_id, operator),
            )

        with open(ROOT / "data" / "pack_sample.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f) if sample_orders else []:
                _as_org(cur, r["org_id"])
                upsert_order(cur, Order(
                    order_id=r["order_id"], organization_id=r["org_id"], unit_id=r["unit_id"],
                    channel=r["channel"], lines=parse_lines(r["order_lines"]),
                ), source="organiser_sample")
                counts[r["org_id"]] = counts.get(r["org_id"], 0) + 1

        for org_id in ORGS:
            path = ROOT / "catalogue" / org_id / "orders.json"
            if path.exists():
                _as_org(cur, org_id)
                for data in json.loads(path.read_text(encoding="utf-8")):
                    upsert_order(cur, Order.model_validate({**data, "organization_id": org_id}), source="own")
                    counts[org_id] = counts.get(org_id, 0) + 1
    conn.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-seed", action="store_true")
    parser.add_argument("--no-sample-orders", action="store_true",
                        help="Don't load the organisers' dummy orders; use real orders only.")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_admin_url:
        raise SystemExit("DATABASE_ADMIN_URL is not set.")
    migrate(settings.database_admin_url, settings.pack_app_db_password)
    print("Schema, policies and pack_app role are in place.")
    if not args.no_seed:
        print("Seeded orders per organisation:", seed(settings.database_admin_url, not args.no_sample_orders))


if __name__ == "__main__":
    main()
