"""Postgres access. Every tenant query runs inside `db.org(org_id)`, which sets the
transaction-local app.org_id that the row-level security policies check."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool

psycopg2.extras.register_uuid()

log = logging.getLogger("pack_manager.db")


class DatabaseBusy(RuntimeError):
    """Every connection stayed in use for too long."""


class Database:
    def __init__(self, dsn: str, maxconn: int = 8, wait_s: float = 30.0):
        self.pool = psycopg2.pool.ThreadedConnectionPool(1, maxconn, dsn)
        # The pool raises PoolError when all connections are out. Wait for one instead.
        self._slots = threading.BoundedSemaphore(maxconn)
        self._wait_s = wait_s

    def _start(self, org_id: str | None):
        """A pooled connection with its transaction started. A hosted database (Neon) drops
        idle connections, so a dead one is thrown away and a fresh one tried, once."""
        for attempt in (1, 2):
            conn = self.pool.getconn()
            try:
                if conn.closed:
                    raise psycopg2.InterfaceError("connection already closed")
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                if org_id is not None:
                    cur.execute("select set_config('app.org_id', %s, true)", (org_id,))
                else:
                    cur.execute("select 1")
                return conn, cur
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self.pool.putconn(conn, close=True)
                if attempt == 2:
                    raise
                log.info("Dropped a dead database connection; opening a new one.")
            except BaseException:
                self.pool.putconn(conn, close=True)
                raise
        raise AssertionError("unreachable")

    @contextmanager
    def _tx(self, org_id: str | None):
        if not self._slots.acquire(timeout=self._wait_s):
            raise DatabaseBusy("The database is busy. Try again in a moment.")
        try:
            conn, cur = self._start(org_id)
            try:
                with conn:  # commit on success, roll back on error
                    with cur:
                        yield cur
            finally:
                self.pool.putconn(conn)
        finally:
            self._slots.release()

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
