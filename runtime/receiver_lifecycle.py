"""Message-less Driver lifecycle identity; not a signed permit or permission.

The Node's existing current-authority callback must independently admit this
operation and exact binding. Production Node verification is not supplied here.
Lifecycle authority can only reach spawn/resume, never ordinary Native input.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from runtime.receiver_lifecycle_read import AuthorizedLifecycleObservation

if TYPE_CHECKING:
    from runtime.codex_driver import BindingIdentity


def _reject(reason):
    from runtime.codex_driver import DriverRejected

    raise DriverRejected(reason)


def lifecycle_operation_id(source_ref: str, action: str, *, restore_process_ref: str | None = None) -> str:
    identity = {"source_kind": "receiver_lifecycle", "source_ref": source_ref, "action": action}
    if restore_process_ref is not None:
        value = restore_process_ref.removeprefix("stopped-process:") if isinstance(restore_process_ref, str) else ""
        if (action != "resume" or not isinstance(restore_process_ref, str)
                or not restore_process_ref.startswith("stopped-process:") or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            _reject("process restoration can only resume the original Native session")
        identity["restore_process_ref"] = restore_process_ref
    value = json.dumps(identity,
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "receiver-lifecycle:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthorizedLifecycleOperation:
    operation_id: str
    command_id: str
    source_ref: str
    grant_ref: str
    deadline: datetime | None
    action: Literal["spawn", "resume"]
    binding_id: str
    binding: BindingIdentity
    native_session_ref: str | None = None
    provider_generation: str | None = None
    restore_process_ref: str | None = None

    @property
    def read_only(self):
        return False

    def validate(self, clock=None):
        from runtime.codex_driver import BindingIdentity

        if (type(self) is not AuthorizedLifecycleOperation or self.action not in {"spawn", "resume"} or type(self.binding) is not BindingIdentity
                or any(type(value) is not str or not value or len(value) > maximum
                       or any(ord(character) < 32 or ord(character) == 127 for character in value)
                       for value, maximum in ((self.command_id, 256), (self.grant_ref, 256),
                           (self.source_ref, 512), (self.binding_id, 512)))
                or self.operation_id != lifecycle_operation_id(self.source_ref, self.action,
                    restore_process_ref=self.restore_process_ref)):
            _reject("complete stable lifecycle source/action/binding identity required")
        self.binding.validate()
        if self.restore_process_ref is not None:
            value = self.restore_process_ref.removeprefix("stopped-process:") if isinstance(self.restore_process_ref, str) else ""
            if (self.action != "resume" or not isinstance(self.restore_process_ref, str)
                    or not self.restore_process_ref.startswith("stopped-process:")
                    or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
                _reject("process restoration requires exact stopped-process evidence")
        if self.action == "resume":
            if any(type(value) is not str or not 1 <= len(value) <= 512
                   for value in (self.native_session_ref, self.provider_generation)):
                _reject("lifecycle resume requires the original Native session/generation")
        elif self.native_session_ref is not None or self.provider_generation is not None:
            _reject("lifecycle spawn cannot replace an existing Native session")
        if self.deadline is not None:
            if not isinstance(self.deadline, datetime) or self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
                _reject("lifecycle deadline requires an aware clock")
            try:
                if clock is not None:
                    clock.require_before(self.deadline)
                elif self.deadline <= datetime.now(UTC):
                    _reject("lifecycle authorization deadline expired")
            except ValueError:
                _reject("lifecycle authorization clock/deadline unavailable")

    def remaining(self, clock=None):
        self.validate(clock)
        if self.deadline is None:
            return float("inf")
        try:
            remaining = clock.remaining(self.deadline) if clock is not None else (self.deadline - datetime.now(UTC)).total_seconds()
        except ValueError:
            _reject("lifecycle authorization clock has no remaining budget")
        if remaining <= 0:
            _reject("lifecycle authorization has no remaining budget")
        return remaining

    def check_target(self, binding_id, binding, native_session_ref, *, action=None, fresh_effect=False):
        if binding_id != self.binding_id or binding != self.binding or action is not None and action != self.action:
            _reject("lifecycle action or immutable Driver binding changed")
        if self.action == "resume":
            from dataclasses import asdict

            from runtime.receiver_contract import native_generation

            if (native_session_ref != self.native_session_ref or self.provider_generation !=
                    native_generation(binding_id, asdict(binding), native_session_ref)):
                _reject("lifecycle Native session/generation changed")
        elif fresh_effect and native_session_ref is not None:
            _reject("lifecycle spawn cannot replace an existing Native session")

    def check_rpc(self, method):
        readonly = {"initialize", "thread/read", "thread/turns/list", "config/read",
                    "experimentalFeature/list", "permissionProfile/list", "mcpServerStatus/list"}
        if method not in readonly | ({"thread/start"} if self.action == "spawn" else {"thread/resume"}):
            _reject("lifecycle identity cannot authorize this Native RPC")

    def check_http(self, method, path):
        if method != "GET" and not (self.action == "spawn" and method == "POST" and path == "/session"):
            _reject("lifecycle identity cannot authorize this Native HTTP action")


def lifecycle_source_fields(operation):
    if isinstance(operation, AuthorizedLifecycleObservation):
        if type(operation) is not AuthorizedLifecycleObservation:
            _reject("lifecycle observation subtypes are not admitted")
        return {"source_kind": "receiver_lifecycle_observation", "source_ref": operation.source_ref}
    if isinstance(operation, AuthorizedLifecycleOperation):
        if type(operation) is not AuthorizedLifecycleOperation:
            _reject("lifecycle operation subtypes are not admitted")
        value = {"source_kind": "receiver_lifecycle", "source_ref": operation.source_ref}
        if operation.restore_process_ref is not None:
            value["restore_process_ref"] = operation.restore_process_ref
        return value
    return {"message_id": operation.message_id}


def check_lifecycle_driver(operation, driver, *, action=None, fresh_effect=False):
    if isinstance(operation, AuthorizedLifecycleObservation):
        if type(operation) is not AuthorizedLifecycleObservation:
            _reject("lifecycle observation subtypes are not admitted")
        operation.check_target(driver.binding_id, driver.identity,
            getattr(driver, "thread_id", None) or getattr(driver, "session_id", None), action=action,
            fresh_effect=fresh_effect)
    if isinstance(operation, AuthorizedLifecycleOperation):
        if type(operation) is not AuthorizedLifecycleOperation:
            _reject("lifecycle operation subtypes are not admitted")
        operation.check_target(driver.binding_id, driver.identity,
            getattr(driver, "thread_id", None) or getattr(driver, "session_id", None), action=action,
            fresh_effect=fresh_effect)
