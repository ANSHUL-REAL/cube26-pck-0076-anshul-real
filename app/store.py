"""Queries. Each function takes a cursor opened with `db.org(...)`; RLS scopes every row."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import psycopg2.extras

from pack_manager.models import EvidenceRecord, Order, OrderLine
from pack_manager.quality import PreparedImage


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def resolve_code(cur, code: str) -> dict | None:
    cur.execute("select * from resolve_access_code(%s)", (hash_code(code),))
    return cur.fetchone()


def org_name(cur, org_id: str) -> str:
    cur.execute("select name from organizations where id = %s", (org_id,))
    row = cur.fetchone()
    return row["name"] if row else org_id


def _order(row) -> Order:
    return Order(
        order_id=row["order_id"], organization_id=row["organization_id"], client_id=row["client_id"],
        unit_id=row["unit_id"], channel=row["channel"],
        lines=[OrderLine(**line) for line in row["lines"]],
    )


def list_orders(cur, query: str | None = None, limit: int = 200) -> list[dict]:
    """Orders with their latest record, newest-unchecked first."""
    cur.execute(
        """
        select o.*, r.record_id, r.decision, r.status, r.captured_at as checked_at
        from orders o
        left join lateral (
            select record_id, decision, status, captured_at from records
            where records.order_id = o.order_id
            order by captured_at desc limit 1
        ) r on true
        where (%(q)s::text is null or o.order_id ilike %(like)s or o.unit_id ilike %(like)s
               or o.lines::text ilike %(like)s)
        order by (r.record_id is not null), o.created_at desc, o.order_id
        limit %(limit)s
        """,
        {"q": query or None, "like": f"%{query or ''}%", "limit": limit},
    )
    return [{**row, "order": _order(row)} for row in cur.fetchall()]


def get_order(cur, order_id: str) -> Order | None:
    cur.execute("select * from orders where order_id = %s", (order_id,))
    row = cur.fetchone()
    return _order(row) if row else None


def upsert_order(cur, order: Order, source: str = "demo") -> None:
    cur.execute(
        """
        insert into orders (organization_id, order_id, client_id, unit_id, channel, lines, source)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (organization_id, order_id) do update
        set client_id = excluded.client_id, unit_id = excluded.unit_id, channel = excluded.channel,
            lines = excluded.lines, source = excluded.source
        """,
        (order.organization_id, order.order_id, order.client_id, order.unit_id, order.channel,
         json.dumps([line.model_dump() for line in order.lines]), source),
    )


def save_record(cur, record: EvidenceRecord, photos: list[PreparedImage]) -> None:
    cur.execute(
        """
        insert into records (record_id, organization_id, order_id, unit_id, decision, status,
                             captured_at, content_hash, record)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (record.record_id, record.organization_id, record.subject.get("order_id"),
         record.subject.get("unit_id"), record.outcome.decision.value, record.status.value,
         record.captured_at, record.content_hash, record.model_dump_json()),
    )
    for p in photos:
        cur.execute(
            """
            insert into images (image_id, organization_id, record_id, sha256, mime, content)
            values (%s, %s, %s, %s, %s, %s)
            """,
            (p.image_id, record.organization_id, record.record_id, p.sha256, p.mime,
             psycopg2.Binary(p.jpeg)),
        )


def update_record(cur, record: EvidenceRecord) -> None:
    cur.execute(
        """
        update records set decision = %s, status = %s, content_hash = %s, record = %s, updated_at = now()
        where record_id = %s
        """,
        (record.outcome.decision.value, record.status.value, record.content_hash,
         record.model_dump_json(), record.record_id),
    )


def get_record(cur, record_id: str) -> EvidenceRecord | None:
    cur.execute("select record from records where record_id = %s", (record_id,))
    row = cur.fetchone()
    return EvidenceRecord.model_validate(row["record"]) if row else None


def list_records(cur, decision: str | None = None, order_id: str | None = None,
                 unit_id: str | None = None, limit: int = 200, query: str | None = None,
                 since: datetime | None = None) -> list[dict]:
    """Newest first. With `since` (for other pods syncing): oldest first from that time on,
    inclusive, so a record sharing the boundary timestamp is never skipped (dedupe by record_id)."""
    order = "asc" if since else "desc"
    cur.execute(
        f"""
        select record_id, order_id, unit_id, decision, status, captured_at,
               record->>'operator_label' as operator_label, jsonb_array_length(record->'overrides') as overrides
        from records
        where (%(d)s::text is null or decision = %(d)s)
          and (%(o)s::text is null or order_id = %(o)s)
          and (%(u)s::text is null or unit_id = %(u)s)
          and (%(s)s::timestamptz is null or captured_at >= %(s)s)
          and (%(q)s::text is null or order_id ilike %(like)s or record_id ilike %(like)s or unit_id ilike %(like)s)
        order by captured_at {order}, record_id {order}
        limit %(limit)s
        """,
        {"d": decision, "o": order_id, "u": unit_id, "s": since, "limit": limit, "q": query or None,
         "like": f"%{query or ''}%"},
    )
    return cur.fetchall()


def find_image_uses(cur, sha256s: list[str]) -> list[dict]:
    """Earlier records in this organisation that used any of these exact photos."""
    if not sha256s:
        return []
    cur.execute(
        """
        select i.sha256, r.record_id, r.order_id
        from images i join records r on r.record_id = i.record_id
        where i.sha256 = any(%s)
        order by r.captured_at
        """,
        (list(sha256s),),
    )
    return [dict(row) for row in cur.fetchall()]


def get_image(cur, image_id: str) -> tuple[str, bytes] | None:
    cur.execute("select mime, content from images where image_id = %s", (image_id,))
    row = cur.fetchone()
    return (row["mime"], bytes(row["content"])) if row else None


def count_records_since(cur, since) -> int:
    cur.execute("select count(*) as n from records where captured_at >= %s", (since,))
    return cur.fetchone()["n"]


def counts_by_decision(cur) -> dict[str, int]:
    cur.execute("select decision, count(*) as n from records group by decision")
    return {r["decision"]: r["n"] for r in cur.fetchall()}
