"""Actual viewer Notice counters; Native providers remain controlled fixtures."""
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event

import psycopg
import pytest

from runtime.communication_client_notice_storage import (
    NoticeStateIdentity,
    read_notice_metadata,
    write_notice_seen,
)
from runtime.communication_client_service import CommunicationClientService
from runtime.communication_notice_projection_storage import (
    adopt_notice_projection_storage,
    notice_cas_revision,
    notice_projection_revision,
    sync_notice_projection,
    verify_notice_projection_storage,
)
from runtime.errors import SchemaAdoptionError
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_notice_storage import noted as noted_fixture
from runtime_tests.test_communication_client_notice_storage import outcome

noted = noted_fixture
comm = comm_fixture
PROJECT = "project-alpha"


@pytest.fixture
def projected(noted):
    with psycopg.connect(noted.f.dsn) as connection:
        adopt_notice_projection_storage(connection)
    noted.f.clients["a"].service.service.authority._communication_notice_projection_available = True
    return noted


def client(note):
    actor = note.f.clients["a"]
    return CommunicationClientService(actor.service, actor.credential_provider())


def test_notice_dto_and_seen_cas_share_one_actual_view_counter(projected):
    own = client(projected)
    first = own.notice(PROJECT, projected.reference)
    seen = own.mark_notice_seen(PROJECT, first["notice_handle"], {"seen": True},
        expected_revision=first["revision"], client_request_id="notice-view")
    assert seen["revision"] == first["revision"] + 1 and seen["seen"]
    with psycopg.connect(projected.f.dsn) as connection:
        connection.execute("UPDATE communication_notices SET code='receiver_unavailable' WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", projected.identity.source())
    current = own.notice(PROJECT, first["notice_handle"])
    assert current["revision"] == seen["revision"] + 1 and current["seen"]
    assert current["reason_code"] == "receiver_unavailable"
    assert own.mark_notice_seen(PROJECT, first["notice_handle"], {"seen": True},
        expected_revision=first["revision"], client_request_id="notice-view") == seen


def test_other_principal_seen_changes_do_not_advance_my_notice_view(projected):
    before = client(projected).notice(PROJECT, projected.reference)
    other = NoticeStateIdentity(projected.identity.tenant_id, PROJECT, "other-trusted-viewer",
                                projected.identity.message_id, projected.identity.recipient)
    with psycopg.connect(projected.f.dsn) as connection, connection.cursor() as cursor:
        source, _created = read_notice_metadata(cursor, other)
        write_notice_seen(cursor, other, True, expected_revision=source, client_request_id="other-view",
                          project_result=outcome(cursor, other), revision_reader=notice_cas_revision)
    assert client(projected).notice(PROJECT, projected.reference) == before


def test_deleted_seen_and_recreated_cell_cannot_reset_notice_revision(projected):
    own = client(projected)
    first = own.notice(PROJECT, projected.reference)
    seen = own.mark_notice_seen(PROJECT, first["notice_handle"], {"seen": True},
        expected_revision=first["revision"], client_request_id="before-delete")
    with psycopg.connect(projected.f.dsn) as connection:
        connection.execute("DELETE FROM communication_client_notice_seen WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND message_id=%s AND recipient=%s", projected.identity.values())
    missing = own.notice(PROJECT, first["notice_handle"])
    assert not missing["seen"] and missing["revision"] == seen["revision"] + 1
    recreated = own.mark_notice_seen(PROJECT, first["notice_handle"], {"seen": True},
        expected_revision=missing["revision"], client_request_id="after-delete")
    assert recreated["revision"] == missing["revision"] + 1 and recreated["seen"]


def test_seen_source_and_public_source_serialize_without_equal_changed_dto_versions(projected):
    before = client(projected).notice(PROJECT, projected.reference)
    entered = Event()

    def public():
        with psycopg.connect(projected.f.dsn) as connection:
            entered.set()
            connection.execute("UPDATE communication_notices SET code='receiver_unavailable' WHERE tenant_id=%s AND project_id=%s AND message_id=%s AND recipient=%s", projected.identity.source())

    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(projected.f.dsn) as private:
        cursor = private.cursor()
        write_notice_seen(cursor, projected.identity, True, expected_revision=before["revision"], client_request_id="interleave",
                          project_result=outcome(cursor, projected.identity), revision_reader=notice_cas_revision)
        future = pool.submit(public)
        assert entered.wait(3)
        with pytest.raises(FutureTimeout):
            future.result(timeout=0.2)
        private.commit()
        future.result(timeout=5)
    after = client(projected).notice(PROJECT, projected.reference)
    assert after["revision"] == before["revision"] + 2 and after["seen"] and after["reason_code"] == "receiver_unavailable"


def test_viewer_counter_getter_freezes_committed_seen_fields(projected):
    entered = Event()

    def seen_writer(expected):
        with psycopg.connect(projected.f.dsn) as connection:
            entered.set()
            write_notice_seen(connection.cursor(), projected.identity, True, expected_revision=expected, client_request_id="blocked-source",
                              project_result=outcome(connection.cursor(), projected.identity), revision_reader=notice_cas_revision)

    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(projected.f.dsn) as reader:
        revision = sync_notice_projection(reader.cursor(), projected.identity)
        future = pool.submit(seen_writer, revision)
        assert entered.wait(3)
        with pytest.raises(FutureTimeout):
            future.result(timeout=0.2)
        assert notice_projection_revision(reader.cursor(), projected.identity) == revision
        assert reader.execute("SELECT seen FROM communication_client_notice_seen WHERE tenant_id=%s AND project_id=%s AND actor_ref=%s AND message_id=%s AND recipient=%s", projected.identity.values()).fetchone() is None
        reader.commit()
        future.result(timeout=5)
    assert client(projected).notice(PROJECT, projected.reference)["revision"] == revision + 1


@pytest.mark.parametrize("damage", ["column", "key", "trigger"])
def test_notice_viewer_schema_damage_requires_explicit_adoption(projected, damage):
    with psycopg.connect(projected.f.dsn) as connection:
        if damage == "column":
            connection.execute("ALTER TABLE communication_notice_view_versions DROP COLUMN seen_revision")
        elif damage == "key":
            connection.execute("ALTER TABLE communication_notice_view_versions DROP CONSTRAINT communication_notice_view_versions_pkey")
        else:
            connection.execute("ALTER TABLE communication_client_notice_seen DISABLE TRIGGER acs_notice_projection_seen")
    with psycopg.connect(projected.f.dsn) as connection, pytest.raises(SchemaAdoptionError):
        verify_notice_projection_storage(connection)
