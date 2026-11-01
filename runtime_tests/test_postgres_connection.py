"""Only pre-query startup EOF is retried; transaction outcomes stay unknown."""
from types import SimpleNamespace

import psycopg
import pytest

from runtime import postgres_connection as module


def test_startup_eof_recovers_with_same_dsn_and_timeout(monkeypatch):
    calls, pauses = [], []
    connection = object()
    def opened(dsn, **kwargs):
        calls.append((dsn, kwargs))
        if len(calls) < 3:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return connection
    monkeypatch.setattr(module.psycopg, "connect", opened)
    monkeypatch.setattr(module.time, "sleep", pauses.append)
    dsn = "postgresql://test@localhost/test?sslmode=require"
    assert module.connect(dsn, options="-cstatement_timeout=900", autocommit=True) is connection
    assert calls == [(dsn, {"options": "-cstatement_timeout=900", "autocommit": True, "connect_timeout": 5})] * 3
    assert pauses == [0.05, 0.1]


@pytest.mark.parametrize("error", [
    psycopg.OperationalError("server closed the connection unexpectedly"),
    psycopg.OperationalError("connection refused"),
    psycopg.errors.InvalidPassword("authentication failed"),
    psycopg.errors.TooManyConnections("too many clients"),
])
def test_startup_retries_are_bounded_and_exclude_server_rejections(monkeypatch, error):
    calls = []
    def opened(*args, **kwargs):
        calls.append(1)
        raise error
    monkeypatch.setattr(module.psycopg, "connect", opened)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with pytest.raises(type(error)):
        module.connect("dbname=test")
    assert len(calls) == (3 if str(error) == "server closed the connection unexpectedly" else 1)


def test_explicit_timeout_and_post_connection_failure_are_not_replayed(monkeypatch):
    calls = []
    def execute():
        raise psycopg.OperationalError("server closed the connection unexpectedly")
    connection = SimpleNamespace(execute=execute)
    def opened(dsn, **kwargs):
        calls.append((dsn, kwargs))
        return connection
    monkeypatch.setattr(module.psycopg, "connect", opened)
    result = module.connect("dbname=test connect_timeout=2", options="-ctimezone=UTC")
    with pytest.raises(psycopg.OperationalError):
        result.execute()
    assert calls == [("dbname=test connect_timeout=2", {"options": "-ctimezone=UTC"})]
