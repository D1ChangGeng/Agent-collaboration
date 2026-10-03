"""UTC facts, process-local durations and calibrated authority connection time."""
from __future__ import annotations

import math
import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo


def duration_clock() -> float:
    # Linux CLOCK_BOOTTIME is monotonic and includes host suspend.
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()


class ClockUnavailable(ValueError):
    """No trustworthy current estimate is available."""


class ClockExpired(ClockUnavailable):
    pass


class ClockUncertain(ClockUnavailable):
    pass


def canonical_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("absolute time must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("absolute time requires an explicit timezone")
    return value.astimezone(UTC)


def present_time(value: datetime, timezone: str = "UTC") -> dict[str, Any]:
    """Return display data while retaining the canonical UTC fact."""
    canonical = canonical_utc(value)
    displayed = canonical.astimezone(ZoneInfo(timezone))
    return {"canonical_utc": canonical.isoformat(), "timezone": timezone,
            "display": displayed.isoformat(), "fold": displayed.fold}


@dataclass(frozen=True, slots=True)
class ClockReading:
    canonical_utc: datetime
    earliest_utc: datetime
    latest_utc: datetime
    uncertainty_seconds: float
    rtt_seconds: float
    offset_seconds: float
    age_seconds: float
    reference_id: str
    identity: Mapping[str, Any]
    clock_id: str
    sample_id: str
    sequence: int


class ConnectionClock:
    """Estimate trusted authority UTC using monotonic round-trip observations.

    The reference callable comes from an authenticated authority connection,
    never from an unverified request timestamp. Estimates are process-local;
    audit snapshots cannot restore a live monotonic anchor after a restart.
    """

    def __init__(
        self, reference_id: str, reference: Callable[[], datetime], *,
        identity: Mapping[str, Any] | None = None,
        monotonic: Callable[[], float] | None = None,
        wall: Callable[[], datetime] | None = None,
        max_age_seconds: float = 30, max_rtt_seconds: float = 2,
        max_uncertainty_seconds: float = 1, drift_ppm: float = 100,
        resolution_seconds: float = 0.000001,
    ):
        if not isinstance(reference_id, str) or not reference_id or not callable(reference):
            raise ClockUnavailable("an authenticated clock reference is required")
        bounds = (max_age_seconds, max_rtt_seconds, max_uncertainty_seconds,
                  drift_ppm, resolution_seconds)
        if any(not math.isfinite(v) or v < 0 for v in bounds) or min(bounds[:3]) <= 0:
            raise ClockUnavailable("connection clock bounds are invalid")
        self.reference_id, self._reference = reference_id, reference
        self.identity = MappingProxyType(dict(identity or {}))
        self._monotonic = monotonic or duration_clock
        self._wall = wall or (lambda: datetime.now(UTC))
        self.max_age_seconds, self.max_rtt_seconds = max_age_seconds, max_rtt_seconds
        self.max_uncertainty_seconds = max_uncertainty_seconds
        self.drift_ppm, self.resolution_seconds = drift_ppm, resolution_seconds
        self.clock_id = uuid.uuid4().hex
        self._process_id = os.getpid()
        self._sample: tuple[datetime, float, float, float, float, str, int] | None = None
        self._sequence = 0
        self._wall_anchor = None
        self._last_monotonic = None
        self._progression_uncertainty = 0.0
        self._lock = threading.RLock()

    @classmethod
    def local(cls, reference=None, *, identity=None, monotonic=None, wall=None, **bounds):
        local_wall = wall or (lambda: datetime.now(UTC))
        return cls("local-authority", reference or local_wall, identity=identity,
                   monotonic=monotonic, wall=local_wall, **bounds)

    @classmethod
    def from_authority(cls, authority, *, identity=None, **bounds):
        context = authority.context
        reference_id = f"domain:{context.authority_id}:{context.authority_incarnation}"
        expected = {"authority_id": context.authority_id,
                    "authority_incarnation": context.authority_incarnation}
        if any(key in (identity or {}) and identity[key] != value for key, value in expected.items()):
            raise ClockUnavailable("clock identity differs from its authenticated authority")
        bound = {**(identity or {}), **expected}
        return cls(reference_id, authority.canonical_now, identity=bound, **bounds)

    def monotonic_now(self) -> float:
        if os.getpid() != self._process_id:
            raise ClockUnavailable("connection clock process identity changed")
        with self._lock:
            observed = float(self._monotonic())
            if not math.isfinite(observed):
                raise ClockUnavailable("monotonic clock is unavailable")
            if self._last_monotonic is not None and observed < self._last_monotonic:
                self._sample = None
                raise ClockUnavailable("monotonic clock domain changed")
            self._last_monotonic = observed
            return observed

    def invalidate(self) -> None:
        with self._lock:
            self._sample = None
            self._wall_anchor = None
            self._last_monotonic = None
            self._progression_uncertainty = 0.0
            self.clock_id = uuid.uuid4().hex
            self._process_id = os.getpid()

    def synchronize(self) -> ClockReading:
        with self._lock:
            start = self.monotonic_now()
            local = canonical_utc(self._wall())
            try:
                authority = canonical_utc(self._reference())
            except Exception as error:
                self._sample = None
                raise ClockUnavailable("authority clock reference is unavailable") from error
            finish = self.monotonic_now()
            rtt = finish - start
            uncertainty = rtt / 2 + self.resolution_seconds
            if rtt < 0 or rtt > self.max_rtt_seconds or uncertainty > self.max_uncertainty_seconds:
                self._sample = None
                raise ClockUncertain("connection clock sample exceeds timing bounds")
            # Reference processing occurred somewhere in the measured interval.
            # Anchoring at its midpoint yields a +/- RTT/2 conservative estimate.
            at_finish = authority + timedelta(seconds=rtt / 2)
            offset = (authority - (local + timedelta(seconds=rtt / 2))).total_seconds()
            self._sequence += 1
            self._sample = (at_finish, finish, uncertainty, rtt, offset,
                            uuid.uuid4().hex, self._sequence)
            self._wall_anchor = (canonical_utc(self._wall()), finish)
            self._progression_uncertainty = 0.0
            return self._reading(finish)

    def _reading(self, now: float) -> ClockReading:
        if self._sample is None:
            raise ClockUnavailable("connection clock has no current sample")
        anchor, observed_mono, initial_uncertainty, rtt, offset, sample_id, sequence = self._sample
        elapsed = now - observed_mono
        if elapsed < 0:
            self._sample = None
            raise ClockUnavailable("monotonic clock domain changed")
        uncertainty = initial_uncertainty + elapsed * self.drift_ppm / 1_000_000 + self._progression_uncertainty
        if elapsed > self.max_age_seconds or uncertainty > self.max_uncertainty_seconds:
            raise ClockUncertain("connection clock sample is stale")
        point = anchor + timedelta(seconds=elapsed)
        radius = timedelta(seconds=uncertainty)
        return ClockReading(point, point - radius, point + radius, uncertainty,
                            rtt, offset, elapsed, self.reference_id, dict(self.identity),
                            self.clock_id, sample_id, sequence)

    def reading(self, refresh: bool = False) -> ClockReading:
        with self._lock:
            if refresh or self._sample is None:
                return self.synchronize()
            now = self.monotonic_now()
            anchor_mono = self._sample[1]
            if now < anchor_mono:
                self._sample = None
                raise ClockUnavailable("monotonic clock domain changed")
            if self._wall_anchor is not None:
                wall_anchor, mono_anchor = self._wall_anchor
                wall_elapsed = (canonical_utc(self._wall()) - wall_anchor).total_seconds()
                # Wall changes never supply corrected time. They only invalidate
                # a potentially suspended/stopped duration clock and request a
                # fresh authenticated authority observation.
                # A progression gap is additional uncertainty, not part of
                # the RTT radius already consumed by reference processing.
                self._progression_uncertainty = abs(wall_elapsed - (now - mono_anchor))
            try:
                return self._reading(now)
            except ClockUncertain:
                return self.synchronize()

    def now(self) -> datetime:
        return self.reading().canonical_utc

    def observation_time(self) -> datetime:
        """Capture a fresh Authority sample for a canonical observed fact.

        The reference is sampled during the call, after the caller's event.
        Its raw UTC stamp preserves causal observation order and cannot lead
        Authority time as a midpoint estimate can within its RTT interval.
        """
        reading = self.synchronize()
        return reading.canonical_utc - timedelta(seconds=reading.rtt_seconds / 2)

    def admission_time(self) -> datetime:
        """Conservative issuer stamp that cannot be future at its authority."""
        return self.reading().earliest_utc

    def require_before(self, deadline: datetime) -> ClockReading:
        expiry = canonical_utc(deadline)
        reading = self.reading()
        if reading.latest_utc < expiry:
            return reading
        reading = self.reading(refresh=True)
        if reading.latest_utc < expiry:
            return reading
        if reading.earliest_utc >= expiry:
            raise ClockExpired("authority deadline has expired")
        raise ClockUncertain("authority deadline overlaps time uncertainty")

    def remaining(self, deadline: datetime) -> float:
        reading = self.require_before(deadline)
        return (canonical_utc(deadline) - reading.latest_utc).total_seconds()

    def fresh(self, issued_at: datetime, expires_at: datetime, max_lifetime: float | None = None) -> bool:
        issued, expiry = canonical_utc(issued_at), canonical_utc(expires_at)
        if expiry <= issued or (max_lifetime is not None and (expiry - issued).total_seconds() > max_lifetime):
            return False
        try:
            reading = self.require_before(expiry)
        except ClockUnavailable:
            return False
        return issued <= reading.latest_utc

    def snapshot(self) -> dict[str, Any]:
        reading = self.reading()
        return {"schema_version": "acs-connection-clock/1",
                "reference_id": reading.reference_id, "identity": dict(reading.identity),
                "clock_id": reading.clock_id, "sample_id": reading.sample_id,
                "sequence": reading.sequence, "canonical_utc": reading.canonical_utc.isoformat(),
                "earliest_utc": reading.earliest_utc.isoformat(), "latest_utc": reading.latest_utc.isoformat(),
                "offset_seconds": reading.offset_seconds, "rtt_seconds": reading.rtt_seconds,
                "uncertainty_seconds": reading.uncertainty_seconds, "age_seconds": reading.age_seconds,
                "recovery": "new calibration required after process, boot or connection replacement"}


TIME_FIELDS = frozenset({"created_at", "issued_at", "completed_at", "observed_at",
                         "updated_at", "expires_at", "deadline", "recorded_at"})


def presentation_metadata(data: Any, timezone: str = "UTC") -> dict[str, Any]:
    """Bounded display sidecar: never rewrite ledger, signatures or API data."""
    ZoneInfo(timezone)
    values = {}
    visited = 0

    def visit(value, path="", depth=0):
        nonlocal visited
        visited += 1
        if depth > 16 or len(values) >= 100 or visited > 1000:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                location = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
                if key in TIME_FIELDS and isinstance(item, (datetime, str)):
                    try:
                        parsed = datetime.fromisoformat(item) if isinstance(item, str) else item
                        values[location] = present_time(parsed, timezone)
                    except (ValueError, OverflowError):
                        pass
                elif isinstance(item, (dict, list)):
                    visit(item, location, depth + 1)
                if len(values) >= 100:
                    break
        elif isinstance(value, list):
            for index, item in enumerate(value[:100]):
                visit(item, path + "/" + str(index), depth + 1)

    visit(data)
    return {"timezone": timezone, "timestamps": values}
