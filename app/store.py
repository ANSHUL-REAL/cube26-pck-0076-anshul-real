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
        unit_id=row["unit_id"], channel=row["channel"], shipment_id=row.get("shipment_id"),
        lines=[OrderLine(**line) for line in row["lines"]],
    )


# Which orders each tab of the orders page shows, by the decision on the order's latest record.
# A record that still needs a person (the AI didn't answer, or it couldn't be sure) keeps the
# order in "To check"; only a settled result (sealed, or stopped to fix) counts as checked.
ORDER_VIEWS = {
    "todo": "(r.decision is null or r.decision in ('PENDING', 'UNCERTAIN'))",
    "done": "r.decision in ('SEAL', 'STOP_AND_FIX')",
    "all": "true",
}

_ORDERS_WITH_LATEST = """
    from orders o
    left join lateral (
        select record_id, decision, status, captured_at from records
        where records.order_id = o.order_id
        order by captured_at desc limit 1
    ) r on true
    where (%(q)s::text is null or o.order_id ilike %(like)s or o.unit_id ilike %(like)s
           or o.lines::text ilike %(like)s)
"""


def list_orders(cur, query: str | None = None, view: str = "all", limit: int = 200) -> list[dict]:
    """Orders with their latest record, newest-unchecked first, for one tab of the orders page."""
    cur.execute(
        f"""
        select o.*, r.record_id, r.decision, r.status, r.captured_at as checked_at
        {_ORDERS_WITH_LATEST}
          and {ORDER_VIEWS[view]}
        order by (r.record_id is not null), o.created_at desc, o.order_id
        limit %(limit)s
        """,
        {"q": query or None, "like": f"%{query or ''}%", "limit": limit},
    )
    return [{**row, "order": _order(row)} for row in cur.fetchall()]


def order_counts(cur, query: str | None = None) -> dict[str, int]:
    """How many orders each tab holds (not capped by the list limit)."""
    cur.execute(
        f"""
        select {", ".join(f'count(*) filter (where {cond}) as "{name}"' for name, cond in ORDER_VIEWS.items())}
        {_ORDERS_WITH_LATEST}
        """,
        {"q": query or None, "like": f"%{query or ''}%"},
    )
    return dict(cur.fetchone())


def get_order(cur, order_id: str) -> Order | None:
    cur.execute("select * from orders where order_id = %s", (order_id,))
    row = cur.fetchone()
    return _order(row) if row else None


def upsert_order(cur, order: Order, source: str = "demo") -> None:
    cur.execute(
        """
        insert into orders (organization_id, order_id, client_id, unit_id, channel, shipment_id, lines, source)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (organization_id, order_id) do update
        set client_id = excluded.client_id, unit_id = excluded.unit_id, channel = excluded.channel,
            shipment_id = excluded.shipment_id, lines = excluded.lines, source = excluded.source
        """,
        (order.organization_id, order.order_id, order.client_id, order.unit_id, order.channel,
         order.shipment_id, json.dumps([line.model_dump() for line in order.lines]), source),
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


def update_record(cur, record: EvidenceRecord, prior_hash: str) -> bool:
    """Save a changed record, but only if it still has the hash it had when it was read.
    False means someone else changed it in the meantime, and nothing was written."""
    cur.execute(
        """
        update records set decision = %s, status = %s, content_hash = %s, record = %s, updated_at = now()
        where record_id = %s and content_hash = %s
        """,
        (record.outcome.decision.value, record.status.value, record.content_hash,
         record.model_dump_json(), record.record_id, prior_hash),
    )
    return cur.rowcount == 1


def get_record(cur, record_id: str) -> EvidenceRecord | None:
    cur.execute("select record from records where record_id = %s", (record_id,))
    row = cur.fetchone()
    return EvidenceRecord.model_validate(row["record"]) if row else None


# A pending record whose photos were sent to the AI again: the newer record is the one to act on.
_RETRIED = """(records.decision = 'PENDING' and exists (
    select 1 from records r2 where r2.record->'observations'->>'retry_of' = records.record_id))"""


def list_records(cur, decision: str | None = None, order_id: str | None = None,
                 unit_id: str | None = None, limit: int = 200, query: str | None = None,
                 since: datetime | None = None) -> list[dict]:
    """Newest first. With `since` (for other pods syncing): oldest first from that time on,
    inclusive, so a record sharing the boundary timestamp is never skipped (dedupe by record_id).
    Filtering on PENDING leaves out records that were already checked again."""
    order = "asc" if since else "desc"
    cur.execute(
        f"""
        select record_id, order_id, unit_id, decision, status, captured_at,
               record->>'operator_label' as operator_label,
               (select count(*) from jsonb_array_elements(record->'overrides') o
                where o->>'check_key' is null) as overrides,  -- decisions on the box, not one check
               {_RETRIED} as retried
        from records
        where (%(d)s::text is null or decision = %(d)s)
          and (%(d)s::text is distinct from 'PENDING' or not {_RETRIED})
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


def find_retry(cur, record_id: str, lock: bool = False) -> str | None:
    """The record made by running the AI check again on this one's photos, if there is one.
    With lock, the original record's row is locked first, so two retries can't both be saved."""
    if lock:
        cur.execute("select 1 from records where record_id = %s for update", (record_id,))
    cur.execute(
        """
        select record_id from records where record->'observations'->>'retry_of' = %s
        order by captured_at limit 1
        """,
        (record_id,),
    )
    row = cur.fetchone()
    return row["record_id"] if row else None


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


def count_ai_checks_since(cur, since) -> int:
    """Boxes the vision model actually answered for (for the daily limit). A box where the
    model failed or wasn't called, or where the answer came from the local cache, isn't counted."""
    cur.execute(
        """
        select count(*) as n from records
        where captured_at >= %s
          and coalesce(record->'overrides'->0->>'original_decision', decision) <> 'PENDING'
          and coalesce((record->'observations'->>'cached_response')::boolean, false) = false
        """,
        (since,),
    )
    return cur.fetchone()["n"]


def counts_by_decision(cur) -> dict[str, int]:
    """Records per decision. Pending records that were checked again are counted as RETRIED,
    so they don't show as waiting for a decision."""
    cur.execute(
        f"""
        select decision, count(*) as n from (
            select case when {_RETRIED} then 'RETRIED' else records.decision end as decision from records
        ) d
        group by decision
        """
    )
    return {r["decision"]: r["n"] for r in cur.fetchall()}


def get_records(cur, record_ids: list[str]) -> dict[str, EvidenceRecord]:
    """Several records in one query, by id."""
    if not record_ids:
        return {}
    cur.execute("select record_id, record from records where record_id = any(%s)", (list(record_ids),))
    return {row["record_id"]: EvidenceRecord.model_validate(row["record"]) for row in cur.fetchall()}


def image_sizes_many(cur, record_ids: list[str]) -> dict[str, dict[str, int]]:
    """Bytes of each stored photo, by record then image id, in one query."""
    out: dict[str, dict[str, int]] = {rid: {} for rid in record_ids}
    if record_ids:
        cur.execute("select record_id, image_id::text as id, octet_length(content) as n from images "
                    "where record_id = any(%s)", (list(record_ids),))
        for row in cur.fetchall():
            out.setdefault(row["record_id"], {})[row["id"]] = row["n"]
    return out


def image_sizes(cur, record_id: str) -> dict[str, int]:
    """Bytes of each stored photo of a record, by image id (for the contract record)."""
    cur.execute("select image_id::text as id, octet_length(content) as n from images where record_id = %s",
                (record_id,))
    return {row["id"]: row["n"] for row in cur.fetchall()}


def records_page(cur, since: datetime | None, after: str | None, limit: int) -> list[str] | None:
    """Record ids in the order they were saved (saved_seq), from `since` (on captured_at) on and
    after the record `after`. Paging on the save order means a check that took longer and was
    saved after a later one is never skipped. None if `after` isn't a record this company can see."""
    seq = None
    if after is not None:
        cur.execute("select saved_seq from records where record_id = %s", (after,))
        row = cur.fetchone()
        if not row:
            return None
        seq = row["saved_seq"]
    cur.execute(
        """
        select record_id from records
        where (%(s)s::timestamptz is null or captured_at >= %(s)s)
          and (%(q)s::bigint is null or saved_seq > %(q)s)
        order by saved_seq
        limit %(limit)s
        """,
        {"s": since, "q": seq, "limit": limit},
    )
    return [row["record_id"] for row in cur.fetchall()]


def legacy_record_ids(cur) -> list[str]:
    """Records saved before record ids became UUIDs (their ids start with PCK-)."""
    cur.execute("select record_id from records where record_id like 'PCK-%'")
    return [row["record_id"] for row in cur.fetchall()]
