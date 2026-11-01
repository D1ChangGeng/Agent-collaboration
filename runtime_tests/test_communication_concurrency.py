"""Concurrent ordinary sends must commit distinct messages without deadlock."""
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication import prepare_ordinary_agents
from runtime_tests.test_delivery import command

comm = comm_fixture


def test_concurrent_independent_requests_to_one_inbox(comm, tmp_path):
    prepare_ordinary_agents(comm, tmp_path)
    client = comm.clients["a"]
    def submit(number):
        return client.service.execute("send_message", {"project_id": "project-alpha",
            "to": "collaborator:project-alpha:slot-b", "content": "concurrent independent request",
            "activation": "message_only", "client_request_id": f"independent-{number}"}, client.credential_provider())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(12)))
    assert len({result[1]["message_handle"] for result in results}) == 12


@pytest.mark.parametrize("statement", [
    "UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref='grant:p1'",
    "UPDATE scopes SET status='revoked' WHERE scope_id='local-scope'",
    "UPDATE authority_instances SET status='revoked' WHERE authority_id='acs-p1-authority'",
])
def test_shared_authorization_read_lock_still_fences_revocation(comm, statement):
    authority = comm.authority
    with authority._connect() as connection, connection.cursor() as cursor:
        authority._authorize(command(authority, "message.read", "target"), cursor, "message.read")
        with psycopg.connect(comm.dsn) as other:
            other.execute("SET lock_timeout=100")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                other.execute(statement)


def test_shared_authorization_readers_can_overlap_before_either_commits(comm):
    authority = comm.authority
    with authority._connect() as first, first.cursor() as cursor:
        authority._authorize(command(authority, "message.read", "first"), cursor, "message.read")
        # The previous UPDATE read locks caused this independent reader to wait.
        with authority._connect() as second, second.cursor() as other:
            other.execute("SET lock_timeout=200")
            authority._authorize(command(authority, "message.read", "second"), other, "message.read")
