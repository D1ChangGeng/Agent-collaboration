"""Owner notification identity follows the actual connection lifecycle."""
import psycopg

from runtime_tests.test_project_service import send_args
from runtime_tests.test_project_continuation import complete_response

pytest_plugins = ("runtime_tests.test_project_continuation",)


def test_owner_notification_survives_old_window_and_follows_replacement(continuation):
    f = continuation
    f.authority.access_mode = "owner"
    sent = f.projects.execute("send_message", send_args(), f.credential)[1]
    complete_response(f, sent["message_id"])
    f.projects.bind_notification_session("project-alpha","owner-session-1","owner-connection-1",f.credential)
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT expires_at FROM collaboration_notification_sessions WHERE session_ref='owner-session-1'").fetchone() == (None,)
        conn.execute("UPDATE collaboration_notification_sessions SET expires_at=clock_timestamp()-interval '1 day'")
    expected = sent["response_handle"] + ":completion:1"
    assert expected in f.projects.pending_wake_keys("project-alpha","owner-session-1","owner-connection-1",f.credential)
    f.projects.bind_notification_session("project-alpha","owner-session-2","owner-connection-2",f.credential)
    assert f.projects.pending_wake_keys("project-alpha","owner-session-1","owner-connection-1",f.credential) == []
    assert expected in f.projects.pending_wake_keys("project-alpha","owner-session-2","owner-connection-2",f.credential)
