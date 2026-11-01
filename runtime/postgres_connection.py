"""Bounded recovery of a disconnected PostgreSQL startup handshake only."""
from __future__ import annotations

import time

import psycopg
from psycopg.conninfo import conninfo_to_dict


def connect(dsn, **kwargs):
    # The caller may choose a stricter/different connection timeout. Do not
    # override its DSN, TLS, authentication or transaction settings.
    if "connect_timeout" not in kwargs and "connect_timeout" not in conninfo_to_dict(dsn):
        kwargs["connect_timeout"] = 5
    for attempt in range(3):
        try:
            return psycopg.connect(dsn, **kwargs)
        except psycopg.OperationalError as error:
            # No connection has been returned and no application query or
            # transaction has run. Never use this retry around execute/commit.
            transient = error.sqlstate is None and any(fragment in str(error).lower() for fragment in (
                "server closed the connection unexpectedly", "connection reset by peer",
                "ssl syscall error: eof detected",
            ))
            if not transient or attempt == 2:
                raise
            time.sleep(0.05 * (2 ** attempt))
