"""Message-less, scoped Native read capability, minted only by a trusted Node.

This shape is not a signed permission. The exact object must remain registered
in its owning Node's short-lived lease; no message or DeliveryAttempt is made.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.codex_driver import BindingIdentity


def _reject():
    from runtime.codex_driver import DriverRejected

    raise DriverRejected("current Node-owned lifecycle read capability required")


@dataclass(frozen=True)
class AuthorizedLifecycleObservation:
    operation_id: str
    command_id: str
    source_ref: str
    grant_ref: str
    deadline: datetime
    binding_id: str
    binding: BindingIdentity
    native_session_ref: str | None
    provider_generation: str | None
    _validate_current: Callable = field(repr=False, compare=False)

    @property
    def read_only(self):
        return True

    def validate(self, clock=None):
        from runtime.codex_driver import BindingIdentity

        if (type(self) is not AuthorizedLifecycleObservation or type(self.binding) is not BindingIdentity
                or not callable(self._validate_current) or not self.operation_id.startswith("receiver-lifecycle-read:")
                or not isinstance(self.deadline, datetime) or self.deadline.tzinfo is None or self.deadline.utcoffset() is None
                or any(type(value) is not str or not 1 <= len(value) <= maximum
                       or any(ord(char) < 32 or ord(char) == 127 for char in value)
                       for value, maximum in ((self.operation_id, 256), (self.command_id, 256),
                           (self.source_ref, 512), (self.grant_ref, 256), (self.binding_id, 512)))):
            _reject()
        self.binding.validate()
        self._validate_current(self, clock)

    def remaining(self, clock=None):
        self.validate(clock)
        if clock is None:
            _reject()
        try:
            return clock.remaining(self.deadline)
        except ValueError:
            _reject()

    def check_target(self, binding_id, binding, native_session_ref, *, action=None, fresh_effect=False):
        from dataclasses import asdict

        from runtime.receiver_contract import native_generation

        if (type(self) is not AuthorizedLifecycleObservation or action is not None or fresh_effect
                or binding_id != self.binding_id or binding != self.binding or native_session_ref != self.native_session_ref
                or (native_session_ref is None) != (self.provider_generation is None)
                or native_session_ref is not None and self.provider_generation != native_generation(binding_id, asdict(binding), native_session_ref)):
            _reject()

    def check_rpc(self, method, params):
        if type(self) is not AuthorizedLifecycleObservation or type(params) is not dict:
            _reject()
        if method in {"thread/read", "thread/turns/list"}:
            if self.native_session_ref is None or params.get("threadId") != self.native_session_ref:
                _reject()
        elif method not in {"config/read", "experimentalFeature/list", "permissionProfile/list", "mcpServerStatus/list"}:
            _reject()

    def check_http(self, method, path):
        routes = {"/doc", "/config", "/session/status", "/permission", "/question"}
        if self.native_session_ref is not None:
            routes.add("/session/" + self.native_session_ref)
        if type(self) is not AuthorizedLifecycleObservation or method != "GET" or path not in routes:
            _reject()
