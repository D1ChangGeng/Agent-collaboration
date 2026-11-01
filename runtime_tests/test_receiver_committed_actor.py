"""Shared technical dispatch recovers only an exact committed sender identity."""
import json
from copy import copy
from dataclasses import replace

import pytest

from runtime.errors import AuthorizationDenied
from runtime.models import CommandEnvelope
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import prepare_ordinary_agents, send

comm = comm_fixture


def committed(comm, tmp_path):
    prepare_ordinary_agents(comm, tmp_path)
    message = send(comm)["data"]
    with comm.authority._connect() as connection:
        row = connection.execute("SELECT command_json FROM delivery_messages WHERE message_id=%s", (message["message_id"],)).fetchone()
    return CommandEnvelope.model_validate_json(json.dumps(row[0]), strict=True)


def test_shared_technical_observer_uses_committed_sender_and_current_grant(comm, tmp_path):
    command = committed(comm, tmp_path)
    with comm.authority._connect() as connection, connection.cursor() as cursor:
        actor = comm.authority.receiver_transport._command_actor(command, cursor)
        assert actor.context.principal_ref == "agent:a-real"
        assert actor.context.grant_ref == command.grant_ref != comm.authority.context.grant_ref
        actor._authorize(command, cursor, "runtime.invoke", "local-scope")
    with comm.authority._connect() as connection:
        connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (command.grant_ref,))
    with comm.authority._connect() as connection, connection.cursor() as cursor:
        actor = comm.authority.receiver_transport._command_actor(command, cursor)
        with pytest.raises(AuthorizationDenied):
            actor._authorize(command, cursor, "runtime.invoke", "local-scope")


@pytest.mark.parametrize("change", [{"principal_ref": "agent:b", "grant_ref": "grant:b"},
    {"command_id": "not-committed"}, {"target_id": "not-committed"}, {"tenant_id": "foreign-tenant"}])
def test_shared_recovery_refuses_altered_committed_command(comm, tmp_path, change):
    command = committed(comm, tmp_path).model_copy(update=change)
    with comm.authority._connect() as connection, connection.cursor() as cursor, pytest.raises(AuthorizationDenied):
        comm.authority.receiver_transport._command_actor(command, cursor)


def test_other_authority_cannot_adopt_an_existing_message_sender(comm, tmp_path):
    command = committed(comm, tmp_path)
    foreign = copy(comm.authority)
    foreign.context = replace(foreign.context, tenant_id="foreign-tenant")
    with comm.authority._connect() as connection, connection.cursor() as cursor, pytest.raises(AuthorizationDenied):
        foreign.receiver_transport._command_actor(command, cursor)
