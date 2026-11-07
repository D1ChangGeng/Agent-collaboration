"""Request-local Core connection reuse, with a separate transaction per check.

The connection can remain open during Node work; a SQL transaction cannot.
No authorization result is cached. Every callback runs the original current
issuer/read/execution checks against fresh committed database state.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy

from psycopg.pq import TransactionStatus

from runtime.receiver_lifecycle_domain import resolve_lifecycle_authority
from runtime.receiver_lifecycle_issuance import require_current_execution
from runtime.receiver_lifecycle_readback import resolve_original_lifecycle_read
from runtime.receiver_recovery_operations import ReceiverRecoveryOperations


class LifecycleCoreCallbacks:
    def __init__(self, projects, *, journal_generation):
        self.projects, self.generation = projects, journal_generation
        self._active = ContextVar("lifecycle_core_connection", default=None)

    @contextmanager
    def session(self):
        if self._active.get() is not None:
            yield
            return
        original = self.projects.service.authority
        if original._transaction_connection is not None:
            raise RuntimeError("lifecycle Core callbacks cannot borrow an outer SQL transaction")
        with original._connect() as connection:
            connection.autocommit = True
            authority = copy(original)
            authority._transaction_connection = connection
            shared, projects = copy(self.projects.service), copy(self.projects)
            shared.authority, projects.service = authority, shared
            recovery = ReceiverRecoveryOperations(projects)
            token = self._active.set((recovery, connection))
            try:
                yield
                self._idle(connection)
            finally:
                self._active.reset(token)

    @staticmethod
    def _idle(connection):
        if connection.closed or connection.info.transaction_status != TransactionStatus.IDLE:
            raise RuntimeError("lifecycle authority check retained an active SQL transaction")

    def _current(self):
        active = self._active.get()
        if active is None:
            raise RuntimeError("lifecycle Core callbacks require their request-local session")
        recovery, connection = active
        self._idle(connection)
        return recovery, connection

    def resolve(self, _stage, source):
        recovery, connection = self._current()
        result = resolve_lifecycle_authority(recovery, source, journal_generation=self.generation)
        self._idle(connection)
        return result

    def execution(self, signed):
        recovery, connection = self._current()
        with recovery.authority.transaction() as (_authority, current), current.cursor() as cursor:
            from runtime.communication_message_wake import lifecycle_store

            store = lifecycle_store(recovery, cursor, signed.permit.plan.source)
            require_current_execution(store, cursor, signed.permit.plan.source.project_id,
                signed.permit.plan.source.operation_ref, signed, journal_generation=self.generation)
        self._idle(connection)

    def read(self, signed):
        recovery, connection = self._current()
        result = resolve_original_lifecycle_read(recovery, signed)
        self._idle(connection)
        return result
