from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DriverCapabilities:
    harness: str
    actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DriverInvocation:
    operation_id: str
    command_id: str
    message_id: str
    agent_slot_id: str


@dataclass(frozen=True, slots=True)
class DriverReceipt:
    operation_id: str
    command_id: str
    message_id: str
    harness: str
    receipt_layer: str
    session_ref: str
    observed_at: datetime


class DriverEndpoint(Protocol):
    def invoke(self, harness: str, invocation: DriverInvocation) -> DriverReceipt: ...


class HarnessDriver:
    harness: str

    def __init__(self, endpoint: DriverEndpoint) -> None:
        self._endpoint = endpoint

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(self.harness, ("invoke", "inspect"))

    def invoke(self, invocation: DriverInvocation) -> DriverReceipt:
        return self._endpoint.invoke(self.harness, invocation)


class CodexDriver(HarnessDriver):
    harness = "codex"


class OpenCodeDriver(HarnessDriver):
    harness = "opencode"
