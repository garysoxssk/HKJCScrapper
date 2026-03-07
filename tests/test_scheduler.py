"""Unit tests for scheduler.py - time computation and rule evaluation logic."""

from datetime import datetime, timedelta, timezone

import pytest

from hkjc_scrapper.models import (
    Match,
    MatchFilter,
    Observation,
    Schedule,
    ScheduleTrigger,
    Team,
    Tournament,
    WatchRule,
)
from hkjc_scrapper.scheduler import (
    MATCH_DURATION_MINUTES,
    compute_event_boundary,
    compute_trigger_time,
    parse_kickoff_time,
)

# Fixed kickoff for tests: 2026-03-10 20:00 HK time
HK_TZ = timezone(timedelta(hours=8))
KICKOFF = datetime(2026, 3, 10, 20, 0, 0, tzinfo=HK_TZ)
KICKOFF_STR = "2026-03-10T20:00:00.000+08:00"


# ============================================================================
# parse_kickoff_time
# ============================================================================

class TestParseKickoffTime:

    def test_parse_standard_format(self):
        dt = parse_kickoff_time("2026-03-10T20:00:00.000+08:00")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 10
        assert dt.hour == 20
        assert dt.minute == 0

    def test_parse_preserves_timezone(self):
        dt = parse_kickoff_time("2026-03-10T20:00:00.000+08:00")
        assert dt.utcoffset() == timedelta(hours=8)

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_kickoff_time("not-a-date")


# ============================================================================
# compute_trigger_time
# ============================================================================

class TestComputeTriggerTime:

    def test_before_kickoff(self):
        result = compute_trigger_time(KICKOFF, "before_kickoff", 30)
        expected = KICKOFF - timedelta(minutes=30)
        assert result == expected

    def test_before_kickoff_no_minutes(self):
        result = compute_trigger_time(KICKOFF, "before_kickoff", None)
        assert result is None

    def test_at_kickoff(self):
        result = compute_trigger_time(KICKOFF, "at_kickoff")
        assert result == KICKOFF

    def test_at_halftime(self):
        result = compute_trigger_time(KICKOFF, "at_halftime")
        expected = KICKOFF + timedelta(minutes=45)
        assert result == expected

    def test_after_kickoff(self):
        result = compute_trigger_time(KICKOFF, "after_kickoff", 60)
        expected = KICKOFF + timedelta(minutes=60)
        assert result == expected

    def test_after_kickoff_no_minutes(self):
        result = compute_trigger_time(KICKOFF, "after_kickoff", None)
        assert result is None

    def test_unknown_event(self):
        result = compute_trigger_time(KICKOFF, "unknown_event")
        assert result is None


# ============================================================================
# compute_event_boundary
# ============================================================================

class TestComputeEventBoundary:

    def test_kickoff(self):
        result = compute_event_boundary(KICKOFF, "kickoff")
        assert result == KICKOFF

    def test_halftime(self):
        result = compute_event_boundary(KICKOFF, "halftime")
        assert result == KICKOFF + timedelta(minutes=45)

    def test_fulltime(self):
        result = compute_event_boundary(KICKOFF, "fulltime")
        assert result == KICKOFF + timedelta(minutes=MATCH_DURATION_MINUTES)

    def test_unknown(self):
        result = compute_event_boundary(KICKOFF, "extra_time")
        assert result is None


# ============================================================================
# MatchScheduler._schedule_observation (unit-level logic tests)
# ============================================================================

def _make_match(
    match_id="50001111",
    front_end_id="FB9999",
    kickoff_str=KICKOFF_STR,
    status="SCHEDULED",
) -> Match:
    """Create a minimal Match for testing."""
    return Match(
        id=match_id,
        frontEndId=front_end_id,
        matchDate="2026-03-10+08:00",
        kickOffTime=kickoff_str,
        status=status,
        updateAt="2026-03-10T10:00:00.000+08:00",
        homeTeam=Team(id="T1", name_en="Team A", name_ch="A隊"),
        awayTeam=Team(id="T2", name_en="Team B", name_ch="B隊"),
        tournament=Tournament(
            id="TN1", code="EPL", name_en="Eng Premier", name_ch="英超"
        ),
    )


class TestSchedulerScheduleLogic:
    """Tests for the scheduling logic via MatchScheduler._schedule_observation."""

    def _make_scheduler(self):
        """Create a MatchScheduler with mocked dependencies."""
        from unittest.mock import MagicMock

        from hkjc_scrapper.scheduler import MatchScheduler

        scheduler = MatchScheduler.__new__(MatchScheduler)
        scheduler.client = MagicMock()
        scheduler.db = MagicMock()
        scheduler.settings = MagicMock()
        scheduler._scheduler = MagicMock()
        scheduler._shutdown_event = MagicMock()
        scheduler._scheduled_keys = set()
        return scheduler

    def test_event_mode_schedules_future_trigger(self):
        """Event trigger in the future gets scheduled."""
        scheduler = self._make_scheduler()
        match = _make_match()
        obs = Observation(
            odds_types=["HAD", "HHA"],
            schedule=Schedule(
                mode="event",
                triggers=[ScheduleTrigger(event="before_kickoff", minutes=30)],
            ),
        )

        # "now" is well before kickoff - 30min
        now = KICKOFF - timedelta(hours=2)
        count = scheduler._schedule_observation(match, obs, now)

        assert count == 1
        scheduler._scheduler.add_job.assert_called_once()

    def test_event_mode_skips_past_trigger(self):
        """Event trigger in the past is not scheduled."""
        scheduler = self._make_scheduler()
        match = _make_match()
        obs = Observation(
            odds_types=["HAD"],
            schedule=Schedule(
                mode="event",
                triggers=[ScheduleTrigger(event="before_kickoff", minutes=30)],
            ),
        )

        # "now" is after kickoff already
        now = KICKOFF + timedelta(hours=1)
        count = scheduler._schedule_observation(match, obs, now)

        assert count == 0
        scheduler._scheduler.add_job.assert_not_called()

    def test_event_mode_deduplicates(self):
        """Same trigger is not scheduled twice."""
        scheduler = self._make_scheduler()
        match = _make_match()
        obs = Observation(
            odds_types=["HAD"],
            schedule=Schedule(
                mode="event",
                triggers=[ScheduleTrigger(event="at_kickoff")],
            ),
        )

        now = KICKOFF - timedelta(hours=1)
        count1 = scheduler._schedule_observation(match, obs, now)
        count2 = scheduler._schedule_observation(match, obs, now)

        assert count1 == 1
        assert count2 == 0  # Deduplicated

    def test_continuous_mode_schedules_interval(self):
        """Continuous mode with valid window gets scheduled."""
        scheduler = self._make_scheduler()
        match = _make_match()
        obs = Observation(
            odds_types=["CHL"],
            schedule=Schedule(
                mode="continuous",
                interval_seconds=300,
                start_event="kickoff",
                end_event="fulltime",
            ),
        )

        # "now" is before kickoff
        now = KICKOFF - timedelta(hours=1)
        count = scheduler._schedule_observation(match, obs, now)

        assert count == 1
        scheduler._scheduler.add_job.assert_called_once()

    def test_continuous_mode_skips_ended_window(self):
        """Continuous mode where window already ended is not scheduled."""
        scheduler = self._make_scheduler()
        match = _make_match()
        obs = Observation(
            odds_types=["CHL"],
            schedule=Schedule(
                mode="continuous",
                interval_seconds=300,
                start_event="kickoff",
                end_event="fulltime",
            ),
        )

        # "now" is well after fulltime
        now = KICKOFF + timedelta(hours=3)
        count = scheduler._schedule_observation(match, obs, now)

        assert count == 0

    def test_multiple_triggers_in_event_mode(self):
        """Multiple triggers all get scheduled if in the future."""
        scheduler = self._make_scheduler()
        match = _make_match()
        obs = Observation(
            odds_types=["HAD"],
            schedule=Schedule(
                mode="event",
                triggers=[
                    ScheduleTrigger(event="before_kickoff", minutes=30),
                    ScheduleTrigger(event="at_kickoff"),
                    ScheduleTrigger(event="at_halftime"),
                ],
            ),
        )

        now = KICKOFF - timedelta(hours=2)
        count = scheduler._schedule_observation(match, obs, now)

        assert count == 3
