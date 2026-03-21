"""Tests for persistent job scheduling (DB layer + scheduler integration)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from hkjc_scrapper.models import (
    Match,
    Observation,
    Schedule,
    ScheduleTrigger,
    Team,
    Tournament,
)

# Fixed kickoff for tests: 2026-03-10 20:00 HK time
HK_TZ = timezone(timedelta(hours=8))
KICKOFF = datetime(2026, 3, 10, 20, 0, 0, tzinfo=HK_TZ)
KICKOFF_STR = "2026-03-10T20:00:00.000+08:00"


def _make_match(
    match_id="50001111",
    front_end_id="FB9999",
    kickoff_str=KICKOFF_STR,
) -> Match:
    return Match(
        id=match_id,
        frontEndId=front_end_id,
        matchDate="2026-03-10+08:00",
        kickOffTime=kickoff_str,
        status="SCHEDULED",
        updateAt="2026-03-10T10:00:00.000+08:00",
        homeTeam=Team(id="T1", name_en="Team A", name_ch="A隊"),
        awayTeam=Team(id="T2", name_en="Team B", name_ch="B隊"),
        tournament=Tournament(
            id="TN1", code="EPL", name_en="Eng Premier", name_ch="英超"
        ),
    )


# ============================================================================
# DB layer tests (mongomock)
# ============================================================================


class TestScheduledJobsDB:
    """Tests for MongoDBClient scheduled_jobs CRUD methods."""

    def test_insert_scheduled_job_event(self, mock_db):
        job = {
            "dedup_key": "50001111:HAD:2026-03-10T19:30:00+08:00",
            "job_type": "event",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 11, 30, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        }
        mock_db.insert_scheduled_job(job)

        doc = mock_db.scheduled_jobs.find_one({"dedup_key": job["dedup_key"]})
        assert doc is not None
        assert doc["job_type"] == "event"
        assert doc["match_id"] == "50001111"
        assert doc["odds_types"] == ["HAD"]

    def test_insert_scheduled_job_continuous(self, mock_db):
        job = {
            "dedup_key": "50001111:CHL:continuous:2026-03-10T20:00:00+08:00",
            "job_type": "continuous",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["CHL"],
            "interval_seconds": 300,
            "start_time": datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 3, 10, 13, 45, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        }
        mock_db.insert_scheduled_job(job)

        doc = mock_db.scheduled_jobs.find_one({"dedup_key": job["dedup_key"]})
        assert doc is not None
        assert doc["job_type"] == "continuous"
        assert doc["interval_seconds"] == 300

    def test_insert_upsert_idempotent(self, mock_db):
        key = "50001111:HAD:2026-03-10T19:30:00+08:00"
        job1 = {
            "dedup_key": key,
            "job_type": "event",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 11, 30, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        }
        job2 = dict(job1)
        job2["front_end_id"] = "FB1234"  # different value

        mock_db.insert_scheduled_job(job1)
        mock_db.insert_scheduled_job(job2)

        count = mock_db.scheduled_jobs.count_documents({})
        assert count == 1
        doc = mock_db.scheduled_jobs.find_one({"dedup_key": key})
        assert doc["front_end_id"] == "FB1234"  # updated

    def test_delete_scheduled_job(self, mock_db):
        key = "50001111:HAD:2026-03-10T19:30:00+08:00"
        mock_db.insert_scheduled_job({
            "dedup_key": key,
            "job_type": "event",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 11, 30, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })

        result = mock_db.delete_scheduled_job(key)
        assert result is True
        assert mock_db.scheduled_jobs.count_documents({}) == 0

    def test_delete_nonexistent_returns_false(self, mock_db):
        result = mock_db.delete_scheduled_job("nonexistent:key")
        assert result is False

    def test_get_all_scheduled_jobs(self, mock_db):
        for i in range(3):
            mock_db.insert_scheduled_job({
                "dedup_key": f"key:{i}",
                "job_type": "event",
                "match_id": f"match{i}",
                "front_end_id": f"FB{i}",
                "odds_types": ["HAD"],
                "trigger_time": datetime(2026, 3, 10, 11 + i, tzinfo=timezone.utc),
                "created_at": datetime.now(timezone.utc),
            })

        jobs = mock_db.get_all_scheduled_jobs()
        assert len(jobs) == 3

    def test_delete_expired_event_jobs(self, mock_db):
        now = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
        # Past event
        mock_db.insert_scheduled_job({
            "dedup_key": "past:event",
            "job_type": "event",
            "match_id": "m1",
            "front_end_id": "FB1",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 11, 0, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })
        # Future event
        mock_db.insert_scheduled_job({
            "dedup_key": "future:event",
            "job_type": "event",
            "match_id": "m2",
            "front_end_id": "FB2",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })

        deleted = mock_db.delete_expired_scheduled_jobs(now)
        assert deleted == 1
        remaining = mock_db.get_all_scheduled_jobs()
        assert len(remaining) == 1
        assert remaining[0]["dedup_key"] == "future:event"

    def test_delete_expired_continuous_jobs(self, mock_db):
        now = datetime(2026, 3, 10, 14, 0, tzinfo=timezone.utc)
        # Past continuous (end_time already passed)
        mock_db.insert_scheduled_job({
            "dedup_key": "past:continuous",
            "job_type": "continuous",
            "match_id": "m1",
            "front_end_id": "FB1",
            "odds_types": ["CHL"],
            "interval_seconds": 300,
            "start_time": datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 3, 10, 13, 45, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })
        # Active continuous (end_time in future)
        mock_db.insert_scheduled_job({
            "dedup_key": "active:continuous",
            "job_type": "continuous",
            "match_id": "m2",
            "front_end_id": "FB2",
            "odds_types": ["CHL"],
            "interval_seconds": 300,
            "start_time": datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 3, 10, 15, 45, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })

        deleted = mock_db.delete_expired_scheduled_jobs(now)
        assert deleted == 1
        remaining = mock_db.get_all_scheduled_jobs()
        assert len(remaining) == 1
        assert remaining[0]["dedup_key"] == "active:continuous"

    def test_delete_expired_keeps_future_jobs(self, mock_db):
        now = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
        mock_db.insert_scheduled_job({
            "dedup_key": "future:event",
            "job_type": "event",
            "match_id": "m1",
            "front_end_id": "FB1",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })

        deleted = mock_db.delete_expired_scheduled_jobs(now)
        assert deleted == 0
        assert mock_db.scheduled_jobs.count_documents({}) == 1


# ============================================================================
# Scheduler persistence tests (mocked dependencies)
# ============================================================================


class TestSchedulerPersistence:
    """Tests for scheduler integration with persistent job scheduling."""

    def _make_scheduler(self, mock_db=None, tg=None):
        from hkjc_scrapper.scheduler import MatchScheduler

        scheduler = MatchScheduler.__new__(MatchScheduler)
        scheduler.client = MagicMock()
        scheduler.db = mock_db or MagicMock()
        scheduler.settings = MagicMock()
        scheduler.settings.TG_FETCH_INCLUDE_ODDS = False
        scheduler.settings.TG_DISCOVERY_INCLUDE_RULES = False
        scheduler._scheduler = MagicMock()
        scheduler._shutdown_event = MagicMock()
        scheduler._scheduled_keys = set()
        scheduler.tg = tg
        return scheduler

    def test_schedule_observation_persists_event_job(self, mock_db):
        scheduler = self._make_scheduler(mock_db=mock_db)
        match = _make_match()
        obs = Observation(
            odds_types=["HAD"],
            schedule=Schedule(
                mode="event",
                triggers=[ScheduleTrigger(event="before_kickoff", minutes=30)],
            ),
        )
        now = KICKOFF - timedelta(hours=2)
        count = scheduler._schedule_observation(match, obs, now)

        assert count == 1
        # Verify persisted to DB
        jobs = mock_db.get_all_scheduled_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_type"] == "event"
        assert jobs[0]["match_id"] == "50001111"
        assert jobs[0]["odds_types"] == ["HAD"]
        assert jobs[0]["trigger_time"] is not None

    def test_schedule_observation_persists_continuous_job(self, mock_db):
        scheduler = self._make_scheduler(mock_db=mock_db)
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
        now = KICKOFF - timedelta(hours=1)
        count = scheduler._schedule_observation(match, obs, now)

        assert count == 1
        jobs = mock_db.get_all_scheduled_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_type"] == "continuous"
        assert jobs[0]["interval_seconds"] == 300
        assert jobs[0]["end_time"] is not None

    def test_execute_fetch_deletes_event_job_from_db(self, mock_db):
        from unittest.mock import patch

        scheduler = self._make_scheduler(mock_db=mock_db)
        dedup_key = "50001111:HAD:2026-03-10T19:30:00+08:00"

        # Pre-insert the job
        mock_db.insert_scheduled_job({
            "dedup_key": dedup_key,
            "job_type": "event",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 11, 30, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })
        scheduler._scheduled_keys.add(dedup_key)

        # Mock the API + parse to return matching match
        match = _make_match()
        scheduler.client.send_detailed_match_list_request.return_value = {"data": {"matches": []}}
        mock_db.save_matches = MagicMock(return_value={"matches_upserted": 1, "odds_snapshots": 1})

        with patch("hkjc_scrapper.scheduler.parse_matches_response", return_value=[match]):
            scheduler.execute_fetch("50001111", "FB9999", ["HAD"], dedup_key=dedup_key)

        # Verify job deleted from DB
        assert mock_db.scheduled_jobs.count_documents({}) == 0
        assert dedup_key not in scheduler._scheduled_keys

    def test_execute_fetch_keeps_active_continuous_job(self, mock_db):
        from unittest.mock import patch

        scheduler = self._make_scheduler(mock_db=mock_db)
        dedup_key = "50001111:CHL:continuous:2026-03-10T20:00:00+08:00"

        mock_db.insert_scheduled_job({
            "dedup_key": dedup_key,
            "job_type": "continuous",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["CHL"],
            "interval_seconds": 300,
            "start_time": datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            "end_time": datetime(2099, 12, 31, 23, 59, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })
        scheduler._scheduled_keys.add(dedup_key)

        match = _make_match()
        mock_db.save_matches = MagicMock(return_value={"matches_upserted": 1, "odds_snapshots": 1})
        with patch("hkjc_scrapper.scheduler.parse_matches_response", return_value=[match]):
            scheduler.execute_fetch("50001111", "FB9999", ["CHL"], dedup_key=dedup_key)

        assert mock_db.scheduled_jobs.count_documents({}) == 1
        assert dedup_key in scheduler._scheduled_keys

    def test_execute_fetch_deletes_expired_continuous_job(self, mock_db):
        from unittest.mock import patch

        scheduler = self._make_scheduler(mock_db=mock_db)
        dedup_key = "50001111:CHL:continuous:2026-03-10T20:00:00+08:00"

        mock_db.insert_scheduled_job({
            "dedup_key": dedup_key,
            "job_type": "continuous",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["CHL"],
            "interval_seconds": 300,
            "start_time": datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc),
            "end_time": datetime(2020, 1, 1, 13, 45, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })
        scheduler._scheduled_keys.add(dedup_key)

        match = _make_match()
        mock_db.save_matches = MagicMock(return_value={"matches_upserted": 1, "odds_snapshots": 1})
        with patch("hkjc_scrapper.scheduler.parse_matches_response", return_value=[match]):
            scheduler.execute_fetch("50001111", "FB9999", ["CHL"], dedup_key=dedup_key)

        # Expired continuous job should be deleted
        assert mock_db.scheduled_jobs.count_documents({}) == 0
        assert dedup_key not in scheduler._scheduled_keys

    def test_reload_schedules_future_event_job(self, mock_db):
        scheduler = self._make_scheduler(mock_db=mock_db)

        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_db.insert_scheduled_job({
            "dedup_key": "future:event",
            "job_type": "event",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["HAD"],
            "trigger_time": future_time,
            "created_at": datetime.now(timezone.utc),
        })

        scheduler._reload_scheduled_jobs()

        scheduler._scheduler.add_job.assert_called_once()
        call_kwargs = scheduler._scheduler.add_job.call_args
        assert call_kwargs.kwargs["kwargs"]["dedup_key"] == "future:event"
        assert "future:event" in scheduler._scheduled_keys

    def test_reload_deletes_expired_event_job(self, mock_db):
        scheduler = self._make_scheduler(mock_db=mock_db)

        past_time = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_db.insert_scheduled_job({
            "dedup_key": "past:event",
            "job_type": "event",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["HAD"],
            "trigger_time": past_time,
            "created_at": datetime.now(timezone.utc),
        })

        scheduler._reload_scheduled_jobs()

        # Expired job should have been cleaned up, not re-scheduled
        scheduler._scheduler.add_job.assert_not_called()
        assert mock_db.scheduled_jobs.count_documents({}) == 0

    def test_reload_schedules_active_continuous_job(self, mock_db):
        scheduler = self._make_scheduler(mock_db=mock_db)

        future_end = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_db.insert_scheduled_job({
            "dedup_key": "active:continuous",
            "job_type": "continuous",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["CHL"],
            "interval_seconds": 300,
            "start_time": datetime.now(timezone.utc) - timedelta(minutes=30),
            "end_time": future_end,
            "created_at": datetime.now(timezone.utc),
        })

        scheduler._reload_scheduled_jobs()

        scheduler._scheduler.add_job.assert_called_once()
        assert "active:continuous" in scheduler._scheduled_keys

    def test_reload_rebuilds_dedup_keys(self, mock_db):
        scheduler = self._make_scheduler(mock_db=mock_db)
        assert len(scheduler._scheduled_keys) == 0

        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        for i in range(3):
            mock_db.insert_scheduled_job({
                "dedup_key": f"key:{i}",
                "job_type": "event",
                "match_id": f"match{i}",
                "front_end_id": f"FB{i}",
                "odds_types": ["HAD"],
                "trigger_time": future_time,
                "created_at": datetime.now(timezone.utc),
            })

        scheduler._reload_scheduled_jobs()

        assert len(scheduler._scheduled_keys) == 3
        assert "key:0" in scheduler._scheduled_keys
        assert "key:1" in scheduler._scheduled_keys
        assert "key:2" in scheduler._scheduled_keys

    def test_start_calls_reload_before_scheduler_start(self):
        """Verify start() calls _reload_scheduled_jobs before _scheduler.start()."""
        from hkjc_scrapper.scheduler import MatchScheduler

        scheduler = MatchScheduler.__new__(MatchScheduler)
        scheduler.client = MagicMock()
        scheduler.db = MagicMock()
        scheduler.settings = MagicMock()
        scheduler.settings.DISCOVERY_INTERVAL_SECONDS = 900
        scheduler._scheduler = MagicMock()
        scheduler._shutdown_event = MagicMock()
        scheduler._scheduled_keys = set()
        scheduler.tg = None

        # Mock _reload to track call order
        call_order = []
        scheduler._reload_scheduled_jobs = lambda: call_order.append("reload")
        original_start = scheduler._scheduler.start
        scheduler._scheduler.start = lambda: call_order.append("scheduler_start")

        scheduler.start()

        assert call_order == ["reload", "scheduler_start"]

    def test_execute_fetch_without_dedup_key_no_cleanup(self, mock_db):
        """execute_fetch with no dedup_key (backward compat) skips cleanup."""
        scheduler = self._make_scheduler(mock_db=mock_db)

        # Insert a job that should NOT be touched
        mock_db.insert_scheduled_job({
            "dedup_key": "untouched",
            "job_type": "event",
            "match_id": "50001111",
            "front_end_id": "FB9999",
            "odds_types": ["HAD"],
            "trigger_time": datetime(2026, 3, 10, 11, 30, tzinfo=timezone.utc),
            "created_at": datetime.now(timezone.utc),
        })

        # execute_fetch without dedup_key
        scheduler.client.send_detailed_match_list_request.side_effect = RuntimeError("API error")
        scheduler.execute_fetch("50001111", "FB9999", ["HAD"])  # no dedup_key

        # Job should still be in DB
        assert mock_db.scheduled_jobs.count_documents({}) == 1
