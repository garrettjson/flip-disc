"""Tests for moon phase calculation."""

from datetime import UTC, datetime, timedelta

from flipdisc.services.moon_phase import SYNODIC_PERIOD, moon_phase, phase_name


class TestMoonPhase:
    def test_known_new_moon(self):
        """Reference date itself should be ~0.0."""
        dt = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)
        assert moon_phase(dt) < 0.01

    def test_known_full_moon(self):
        """Half a synodic period after reference should be ~0.5."""
        dt = datetime(2000, 1, 6, 18, 14, tzinfo=UTC) + timedelta(
            days=SYNODIC_PERIOD / 2
        )
        p = moon_phase(dt)
        assert 0.49 < p < 0.51

    def test_range(self):
        """Phase should always be in [0.0, 1.0)."""
        for days_offset in range(365):
            dt = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=days_offset)
            p = moon_phase(dt)
            assert 0.0 <= p < 1.0

    def test_monotonic_first_half(self):
        """Phase should increase monotonically during the first half of a cycle."""
        start = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)
        phases = []
        for hour in range(0, int(SYNODIC_PERIOD * 24 / 2), 6):
            dt = start + timedelta(hours=hour)
            phases.append(moon_phase(dt))
        for i in range(1, len(phases)):
            assert phases[i] > phases[i - 1], (
                f"Phase should increase: {phases[i - 1]} -> {phases[i]}"
            )

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetime should be treated as UTC."""
        dt_naive = datetime(2024, 6, 15, 12, 0)
        dt_utc = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
        assert moon_phase(dt_naive) == moon_phase(dt_utc)

    def test_none_returns_current(self):
        """Calling with None should not raise."""
        p = moon_phase()
        assert 0.0 <= p < 1.0


class TestPhaseName:
    def test_new_moon(self):
        assert phase_name(0.0) == "new_moon"

    def test_waxing_crescent(self):
        assert phase_name(0.125) == "waxing_crescent"

    def test_first_quarter(self):
        assert phase_name(0.25) == "first_quarter"

    def test_waxing_gibbous(self):
        assert phase_name(0.375) == "waxing_gibbous"

    def test_full_moon(self):
        assert phase_name(0.5) == "full_moon"

    def test_waning_gibbous(self):
        assert phase_name(0.625) == "waning_gibbous"

    def test_last_quarter(self):
        assert phase_name(0.75) == "last_quarter"

    def test_waning_crescent(self):
        assert phase_name(0.875) == "waning_crescent"

    def test_wraps_near_one(self):
        assert phase_name(0.97) == "new_moon"
