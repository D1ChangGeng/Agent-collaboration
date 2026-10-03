from datetime import UTC, datetime, timedelta

import pytest

from runtime.connection_clock import (
    ClockExpired,
    ClockUnavailable,
    ClockUncertain,
    ConnectionClock,
    canonical_utc,
    present_time,
)


class FakeTime:
    def __init__(self, offset=0, rtt=0.02):
        self.origin = datetime(2026, 1, 1, tzinfo=UTC)
        self.mono = 100.0
        self.offset, self.rtt, self.calls = offset, rtt, 0

    def wall(self):
        return self.origin + timedelta(seconds=self.mono + self.offset)

    def reference(self):
        self.calls += 1
        instant = self.origin + timedelta(seconds=self.mono + self.rtt / 2)
        self.mono += self.rtt
        return instant

    def clock(self, **kwargs):
        return ConnectionClock("domain:test:incarnation", self.reference,
                               identity={"node_id": "node", "boot_incarnation": "boot"},
                               monotonic=lambda: self.mono, wall=self.wall, **kwargs)


@pytest.mark.parametrize("offset", [-86400, -7200, 0, 7200, 86400])
def test_connection_clock_corrects_host_skew_without_changing_authority_deadlines(offset):
    source = FakeTime(offset)
    clock = source.clock()
    reading = clock.reading()
    assert reading.earliest_utc <= source.origin + timedelta(seconds=source.mono) <= reading.latest_utc
    assert reading.offset_seconds == pytest.approx(-offset)
    expiry = source.origin + timedelta(seconds=source.mono + 30)
    assert clock.require_before(expiry).latest_utc < expiry
    source.mono += 31
    with pytest.raises(ClockExpired):
        clock.require_before(expiry)


def test_wall_clock_steps_do_not_change_elapsed_duration_or_authority_time():
    source = FakeTime()
    clock = source.clock()
    first = clock.now()
    expiry = first + timedelta(seconds=20)
    source.offset += 3600
    source.mono += 5
    assert (clock.now() - first).total_seconds() == pytest.approx(5.02)
    assert clock.remaining(expiry) == pytest.approx(14.969999, abs=0.001)
    source.offset -= 7200
    source.mono += 5
    assert (clock.now() - first).total_seconds() == pytest.approx(10.04)


def test_excessive_rtt_or_uncertainty_cannot_create_usable_freshness():
    source = FakeTime(rtt=4)
    with pytest.raises(ClockUncertain):
        source.clock().reading()
    source = FakeTime(rtt=0.6)
    with pytest.raises(ClockUncertain):
        source.clock(max_uncertainty_seconds=0.2).reading()


def test_expiration_overlap_refreshes_and_remains_uncertain():
    source = FakeTime(rtt=0.2)
    clock = source.clock()
    reading = clock.reading()
    # Slow reply means a timestamp slightly ahead of the estimate is still unsafe.
    source.rtt = 0.4
    with pytest.raises((ClockUncertain, ClockExpired)):
        clock.require_before(reading.canonical_utc + timedelta(seconds=0.05))
    assert source.calls == 2


def test_stale_samples_refresh_and_process_restart_does_not_restore_anchor():
    source = FakeTime()
    clock = source.clock(max_age_seconds=2)
    first = clock.snapshot()
    source.mono += 3
    second = clock.snapshot()
    assert source.calls == 2
    assert second["sequence"] > first["sequence"]
    replacement = source.clock()
    assert replacement.snapshot()["clock_id"] != first["clock_id"]
    assert "monotonic" not in first and "anchor" not in first


def test_monotonic_domain_replacement_invalidates_existing_sample():
    source = FakeTime()
    clock = source.clock()
    clock.reading()
    source.mono -= 10
    with pytest.raises(ClockUnavailable, match="domain changed"):
        clock.reading()


def test_unavailable_authority_never_falls_back_to_host_wall_clock():
    source = FakeTime(offset=86400)
    clock = source.clock()
    clock._reference = lambda: (_ for _ in ()).throw(OSError("offline"))
    with pytest.raises(ClockUnavailable, match="reference is unavailable"):
        clock.now()


def test_freshness_uses_corrected_interval_and_allows_idempotent_cached_facts():
    source = FakeTime(offset=-3600)
    clock = source.clock()
    now = clock.now()
    assert clock.fresh(now - timedelta(seconds=300), now + timedelta(seconds=60))
    assert not clock.fresh(now + timedelta(seconds=5), now + timedelta(seconds=60))
    assert not clock.fresh(now - timedelta(seconds=3), now + timedelta(seconds=1), max_lifetime=2)


def test_absolute_time_rejects_naive_and_normalizes_known_offsets():
    with pytest.raises(ValueError, match="timezone"):
        canonical_utc(datetime(2026, 1, 1))  # noqa: DTZ001 - intentional invalid input
    source = datetime.fromisoformat("2026-01-01T09:00:00+09:00")
    assert canonical_utc(source) == datetime(2026, 1, 1, tzinfo=UTC)


def test_presentation_dst_fold_changes_display_not_canonical_utc():
    try:
        first = present_time(datetime(2026, 11, 1, 5, 30, tzinfo=UTC), "America/New_York")
        second = present_time(datetime(2026, 11, 1, 6, 30, tzinfo=UTC), "America/New_York")
    except KeyError:
        pytest.skip("IANA timezone database unavailable on this host")
    assert first["display"].startswith("2026-11-01T01:30")
    assert second["display"].startswith("2026-11-01T01:30")
    assert first["fold"] == 0 and second["fold"] == 1
    assert first["canonical_utc"] != second["canonical_utc"]


def test_forked_clock_cannot_reuse_parent_calibration(monkeypatch):
    source = FakeTime()
    clock = source.clock()
    original = clock.snapshot()
    monkeypatch.setattr("runtime.connection_clock.os.getpid", lambda: clock._process_id + 1)
    with pytest.raises(ClockUnavailable, match="process identity"):
        clock.reading()
    clock.invalidate()
    # Bind the simulated child PID consistently after explicit re-connection.
    monkeypatch.setattr("runtime.connection_clock.os.getpid", lambda: clock._process_id)
    assert clock.snapshot()["clock_id"] != original["clock_id"]


def test_suspended_duration_source_forces_trusted_refresh_instead_of_stale_freshness():
    source = FakeTime()
    clock = source.clock()
    initial = clock.now()
    expiry = initial + timedelta(seconds=60)
    # A suspended monotonic source stays fixed while UTC advances.
    original_reference = source.reference
    source.offset += 3600
    clock._reference = lambda: original_reference() + timedelta(hours=1)
    with pytest.raises(ClockExpired):
        clock.require_before(expiry)
    assert source.calls >= 2


def test_monotonic_rewind_above_original_anchor_is_still_invalid():
    source = FakeTime()
    clock = source.clock()
    clock.reading()
    source.mono += 20
    clock.reading()
    source.mono -= 10
    with pytest.raises(ClockUnavailable, match="domain changed"):
        clock.now()


def test_subsecond_suspend_cannot_extend_a_short_authority_deadline():
    source = FakeTime(rtt=0)
    clock = source.clock()
    original = clock.now()
    source.offset += 0.5
    original_reference = source.reference
    clock._reference = lambda: original_reference() + timedelta(seconds=0.5)
    with pytest.raises(ClockExpired):
        clock.require_before(original + timedelta(seconds=0.25))


def test_reference_rtt_radius_cannot_absorb_a_separate_suspend_gap():
    source = FakeTime(rtt=1)
    def authority_at_start():
        result = source.origin + timedelta(seconds=source.mono)
        source.mono += source.rtt
        return result
    clock = ConnectionClock("authority", authority_at_start,
                            monotonic=lambda: source.mono, wall=source.wall)
    clock.reading()
    # Actual authority now lies at the initial estimate's upper RTT boundary.
    source.offset += 0.4
    clock._reference = lambda: authority_at_start() + timedelta(seconds=0.4)
    with pytest.raises((ClockExpired, ClockUncertain)):
        clock.require_before(source.origin + timedelta(seconds=101.2))


@pytest.mark.parametrize("position", ["start", "end"])
def test_fact_observation_uses_fresh_reference_sample_and_preserves_causal_order(position):
    source = FakeTime(rtt=0.6)
    def reference():
        started = source.origin + timedelta(seconds=source.mono)
        source.mono += source.rtt
        return (started if position == "start"
                else source.origin + timedelta(seconds=source.mono))
    clock = ConnectionClock("authority", reference, monotonic=lambda: source.mono,
                            wall=source.wall)
    clock.reading()
    completed = source.origin + timedelta(seconds=source.mono)
    observed = clock.observation_time()
    authority_now = source.origin + timedelta(seconds=source.mono)
    assert completed <= observed <= authority_now
    if position == "end":
        assert observed == authority_now
        assert clock.now() > authority_now  # The estimated centre is not a fact stamp.
