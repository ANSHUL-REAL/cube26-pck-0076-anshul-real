"""Postgres access. Every tenant query runs inside `db.org(org_id)`, which sets the
transaction-local app.org_id that the row-level security policies check."""

from __future__ import annotations

from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

psycopg2.extras.register_uuid()


class Database:
    def __init__(self, dsn: str, maxconn: int = 8):
        self.pool = psycopg2.pool.ThreadedConnectionPool(1, maxconn, dsn)

    @contextmanager
    def _tx(self, org_id: str | None):
        conn = self.pool.getconn()
        try:
            with conn:  # commit on success, roll back on error
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if org_id is not None:
                        cur.execute("select set_config('app.org_id', %s, true)", (org_id,))
                    yield cur
        finally:
            self.pool.putconn(conn)

    def org(self, org_id: str):
        """A transaction that can only see and write this organisation's rows."""
        if not org_id:
            raise ValueError("organization id is required")
        return self._tx(org_id)

    def anonymous(self):
        """A transaction with no tenant set: tenant tables return zero rows."""
        return self._tx(None)

    def close(self):
        self.pool.closeall()
