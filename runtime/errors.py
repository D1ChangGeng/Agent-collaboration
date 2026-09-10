from dataclasses import dataclass


class RuntimeErrorBase(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AuthorizationDenied(RuntimeErrorBase):
    principal_ref: str
    grant_ref: str

    def __str__(self) -> str:
        return f"authorization denied for {self.principal_ref} with {self.grant_ref}"


@dataclass(frozen=True, slots=True)
class RevisionConflict(RuntimeErrorBase):
    target_id: str
    expected: int
    actual: int

    def __str__(self) -> str:
        return f"revision conflict for {self.target_id}: expected {self.expected}, actual {self.actual}"


@dataclass(frozen=True, slots=True)
class IdempotencyConflict(RuntimeErrorBase):
    idempotency_key: str

    def __str__(self) -> str:
        return f"idempotency key reused with different payload: {self.idempotency_key}"


@dataclass(frozen=True, slots=True)
class InvalidTransition(RuntimeErrorBase):
    from_state: str
    to_state: str

    def __str__(self) -> str:
        return f"invalid work-item transition {self.from_state} -> {self.to_state}"


@dataclass(frozen=True, slots=True)
class AcceptanceGuardFailed(RuntimeErrorBase):
    reason: str

    def __str__(self) -> str:
        return f"acceptance guard failed: {self.reason}"


@dataclass(frozen=True, slots=True)
class LeaseRejected(RuntimeErrorBase):
    resource_id: str
    reason: str

    def __str__(self) -> str:
        return f"lease rejected for {self.resource_id}: {self.reason}"


@dataclass(frozen=True, slots=True)
class FencingRejected(RuntimeErrorBase):
    resource_id: str

    def __str__(self) -> str:
        return f"fencing rejected for {self.resource_id}"


@dataclass(frozen=True, slots=True)
class NotFound(RuntimeErrorBase):
    kind: str
    target_id: str

    def __str__(self) -> str:
        return f"{self.kind} {self.target_id} not found"
