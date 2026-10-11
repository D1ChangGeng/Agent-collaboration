"""Real PostgreSQL owner flow retains replay and object boundaries after legacy expiry."""
import psycopg
import pytest

from runtime.errors import IdempotencyConflict, NotFound
from runtime_tests.test_project_service import send_args, work_args

pytest_plugins = ("runtime_tests.test_project_service",)


def expired_owner(project):
    project.authority.access_mode = "owner"
    with psycopg.connect(project.dsn) as connection:
        connection.execute("UPDATE grants SET expires_at=clock_timestamp()-interval '1 day',permissions='[]'::jsonb")
    return project


def test_expired_role_metadata_does_not_remove_owner_tools_or_projects(project):
    f = expired_owner(project)
    assert "send_message" in f.projects.available_tools(f.credential)
    assert f.projects.execute("read_profile", {}, f.credential)[1]["connection_state"] == "authorized"
    assert f.projects.execute("list_projects", {}, f.credential)[1]["items"][0]["project_id"] == "project-alpha"


def test_owner_creates_work_without_expiring_command_and_replays_once(project):
    f = expired_owner(project)
    args = work_args()
    args.pop("deadline")
    first = f.projects.execute("create_work", args, f.credential)
    assert first == f.projects.execute("create_work", args, f.credential)
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM work_items WHERE work_item_id='mcp-work'").fetchone()[0] == 1
    with pytest.raises(IdempotencyConflict):
        f.projects.execute("create_work", dict(args, goal="changed replay"), f.credential)


def test_owner_still_cannot_address_an_unknown_project(project):
    f = expired_owner(project)
    with pytest.raises(NotFound):
        f.projects.execute("load_project", {"project_id":"missing-project"}, f.credential)


def test_owner_submits_unbounded_message_after_old_endpoint_expiry(project):
    from runtime.delivery import DeliveryDispatcher
    f = expired_owner(project)
    args = work_args()
    args.pop("deadline")
    f.projects.execute("create_work", args, f.credential)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE delivery_endpoints SET expires_at=clock_timestamp()-interval '1 day'")
    sending = dict(send_args(), activation="invoke")
    sending.pop("deadline", None)
    result = f.projects.execute("send_message", sending, f.credential)
    data = result[1]
    with psycopg.connect(f.dsn) as connection:
        row = connection.execute("SELECT message_id,tenant_id,operation_id,deadline FROM delivery_messages").fetchone()
    assert row[3] is None
    outcome = DeliveryDispatcher(f.service).dispatch({"message_id":row[0],"tenant_id":row[1],"operation_id":row[2]})
    with psycopg.connect(f.dsn) as connection:
        failure = connection.execute("SELECT last_error FROM delivery_messages").fetchone()
    assert outcome["status"] == "delivered", (outcome, failure)
    assert len(f.driver.calls) == 1
    assert f.projects.execute("send_message", sending, f.credential)[1]["message_id"] == data["message_id"]
    assert len(f.driver.calls) == 1


def test_owner_team_is_business_configuration_without_permission_budgets(project):
    f = expired_owner(project)
    args = {"client_request_id":"owner-team", "project_id":"project-alpha",
        "scope_handle":"scope:project-alpha:local-scope", "expected_revision":0,
        "members":[{"agent_slot_id":"owner-engineer", "principal_ref":"agent:owner-engineer",
                    "role":"engineer", "harness_requirements":["codex"]}]}
    schema = f.mcp.input_schema("configure_team")
    assert not {"deadline","policies","budgets"}.intersection(schema["required"])
    result = f.mcp.call("configure_team", args)
    if result["isError"]:
        f.projects.execute("configure_team", args, f.credential)
    assert not result["isError"], result["structuredContent"]
    members = f.projects.execute("list_collaborators", {"project_id":"project-alpha"}, f.credential)[1]["items"]
    assert members[0]["state"] == "active"
    assert members[0]["expires_at"] is None
    with psycopg.connect(f.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM grant_delegations").fetchone()[0] == 0
        assert connection.execute("SELECT permissions,expires_at,identity_only FROM grants WHERE principal_ref='agent:owner-engineer'").fetchone() == ([], None, True)


def test_owner_explicit_revocation_is_not_restored_by_continuous_access(project):
    from runtime.errors import AuthorizationDenied
    f = expired_owner(project)
    with psycopg.connect(f.dsn) as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp()")
    with pytest.raises(AuthorizationDenied):
        f.projects.execute("create_work", work_args(), f.credential)


def test_owner_adoption_preserves_deliberate_revocation(project):
    from runtime.owner_upgrade import migrate_owner_records
    f = expired_owner(project)
    with psycopg.connect(f.dsn) as conn:
        conn.execute("INSERT INTO grants(grant_ref,tenant_id,principal_ref,authority_id,authority_incarnation,scope_id,permissions,expires_at,revoked_at) "
            "SELECT 'revoked-old-actor',tenant_id,'old-actor',authority_id,authority_incarnation,scope_id,'[]',expires_at,clock_timestamp() "
            "FROM grants WHERE grant_ref=%s", (f.authority.context.grant_ref,))
    migrate_owner_records(f.authority)
    migrate_owner_records(f.authority)
    with psycopg.connect(f.dsn) as conn:
        assert conn.execute("SELECT expires_at FROM grants WHERE grant_ref=%s", (f.authority.context.grant_ref,)).fetchone()[0] is None
        row = conn.execute("SELECT expires_at,revoked_at FROM grants WHERE grant_ref='revoked-old-actor'").fetchone()
        assert row[0] is not None and row[1] is not None


def test_owner_mcp_accepts_explicit_null_business_deadline(project):
    f = expired_owner(project)
    args = dict(work_args(), deadline=None)
    reply = f.mcp.call("create_work", args)
    assert not reply["isError"], reply["structuredContent"]


def test_owner_transport_loss_recovers_after_legacy_attempt_budget(project):
    from runtime.delivery import DeliveryDispatcher
    from runtime.delivery_node import DeliveryTransportError
    f=expired_owner(project)
    f.projects.execute("create_work",work_args(),f.credential)
    sent=f.projects.execute("send_message",send_args(),f.credential)[1]
    original=f.endpoint.deliver
    calls=[]
    def unavailable(*args,**kwargs):
        calls.append(1)
        raise DeliveryTransportError("fixture machine temporarily unavailable")
    f.endpoint.deliver=unavailable
    dispatcher=DeliveryDispatcher(f.service)
    identity={"tenant_id":f.authority.tenant_id,"message_id":sent["message_id"],"operation_id":sent["operation_id"]}
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE delivery_messages SET maximum_attempts=1")
    assert dispatcher.dispatch(identity)["status"]=="retry_wait"
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE delivery_messages SET next_attempt_at=clock_timestamp()-interval '1 second'")
    assert dispatcher.dispatch(identity)["status"]=="retry_wait"
    f.endpoint.deliver=original
    with psycopg.connect(f.dsn) as conn:
        conn.execute("UPDATE delivery_messages SET next_attempt_at=clock_timestamp()-interval '1 second'")
    assert dispatcher.dispatch(identity)["status"]=="delivered"
    assert calls==[1,1]
    assert len(f.journal.list_mailbox())==1
