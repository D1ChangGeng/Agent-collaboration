"""Business expiry is optional; internal transport timeouts remain independent."""
from datetime import datetime


def earliest(*values: datetime | None) -> datetime | None:
    finite = [value for value in values if value is not None]
    return min(finite) if finite else None


def expired(value: datetime | None, now: datetime) -> bool:
    return value is not None and value <= now
