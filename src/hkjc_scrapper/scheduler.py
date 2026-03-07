"""Rule-based scheduler for HKJC odds fetching.

Two-layer architecture:
  Layer 1 (Discovery): Periodic job that discovers matches matching watch rules
    and schedules/updates fetch jobs.
  Layer 2 (Fetch): One-shot or interval jobs that actually call API, parse, save.

Tournament discovery is also run during each discovery cycle.
"""

import logging
import signal
import threading
from datetime import datetime, timedelta, timezone

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.config import Settings
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.models import Match, Observation, WatchRule
from hkjc_scrapper.parser import (
    filter_matches_by_rule,
    get_match_description,
    parse_matches_response,
)

logger = logging.getLogger(__name__)

# HK timezone offset (+08:00)
HK_TZ = timezone(timedelta(hours=8))

# How long a match typically lasts (used for fulltime estimates)
MATCH_DURATION_MINUTES = 105  # 90 min + 15 min added time buffer


def parse_kickoff_time(kickoff_str: str) -> datetime:
    """Parse HKJC kickOffTime string into a timezone-aware datetime.

    The API returns times like '2026-03-01T20:00:00.000+08:00'.

    Args:
        kickoff_str: ISO-format kickoff time string from API

    Returns:
        timezone-aware datetime
    """
    return datetime.fromisoformat(kickoff_str)


def compute_trigger_time(
    kickoff: datetime, trigger_event: str, minutes: int | None = None
) -> datetime | None:
    """Compute absolute trigger time from a kickoff time and trigger event.

    Args:
        kickoff: Match kickoff datetime
        trigger_event: One of 'before_kickoff', 'at_kickoff', 'at_halftime',
                       'after_kickoff'
        minutes: Number of minutes (for before_kickoff / after_kickoff)

    Returns:
        Absolute datetime for the trigger, or None if invalid
    """
    if trigger_event == "before_kickoff":
        if minutes is None:
            return None
        return kickoff - timedelta(minutes=minutes)
    elif trigger_event == "at_kickoff":
        return kickoff
    elif trigger_event == "at_halftime":
        return kickoff + timedelta(minutes=45)
    elif trigger_event == "after_kickoff":
        if minutes is None:
            return None
        return kickoff + timedelta(minutes=minutes)
    else:
        logger.warning("Unknown trigger event: %s", trigger_event)
        return None


def compute_event_boundary(kickoff: datetime, event_name: str) -> datetime | None:
    """Compute absolute time for a named match event.

    Used for continuous mode start_event / end_event boundaries.

    Args:
        kickoff: Match kickoff datetime
        event_name: One of 'kickoff', 'halftime', 'fulltime'

    Returns:
        Absolute datetime, or None if unknown event
    """
    if event_name == "kickoff":
        return kickoff
    elif event_name == "halftime":
        return kickoff + timedelta(minutes=45)
    elif event_name == "fulltime":
        return kickoff + timedelta(minutes=MATCH_DURATION_MINUTES)
    else:
        logger.warning("Unknown event boundary: %s", event_name)
        return None


class MatchScheduler:
    """Rule-based match scheduler with discovery + fetch layers."""

    def __init__(
        self,
        client: HKJCGraphQLClient,
        db: MongoDBClient,
        settings: Settings,
    ):
        self.client = client
        self.db = db
        self.settings = settings
        self._scheduler = BackgroundScheduler()
        self._shutdown_event = threading.Event()
        # Track scheduled job IDs to avoid duplicates: set of
        # "matchId:oddsTypes:triggerTime"
        self._scheduled_keys: set[str] = set()

    # ========================================================================
    # Lifecycle
    # ========================================================================

    def start(self):
        """Start the scheduler with the discovery job loop."""
        self._scheduler.add_listener(
            self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        # Schedule the recurring discovery job
        self._scheduler.add_job(
            self.run_discovery,
            trigger=IntervalTrigger(
                seconds=self.settings.DISCOVERY_INTERVAL_SECONDS
            ),
            id="discovery",
            name="Discovery Job",
            next_run_time=datetime.now(timezone.utc),  # Run immediately
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "Scheduler started (discovery every %ds)",
            self.settings.DISCOVERY_INTERVAL_SECONDS,
        )

    def stop(self):
        """Graceful shutdown."""
        logger.info("Shutting down scheduler...")
        self._shutdown_event.set()
        self._scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")

    def wait(self):
        """Block until shutdown signal received (SIGINT/SIGTERM)."""
        self._shutdown_event.wait()

    def setup_signal_handlers(self):
        """Register SIGINT/SIGTERM handlers for graceful shutdown."""
        def _handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info("Received %s, initiating shutdown...", sig_name)
            self.stop()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)

    def _on_job_event(self, event):
        """Handle APScheduler job events for logging."""
        if event.exception:
            logger.error("Job %s failed: %s", event.job_id, event.exception)

    # ========================================================================
    # Layer 1: Discovery
    # ========================================================================

    def run_discovery(self):
        """
        Discovery job: fetch match list, evaluate rules, schedule fetch jobs.

        Also refreshes tournament reference data.
        """
        logger.info("[Discovery] Running discovery cycle...")

        try:
            # 1. Refresh tournament data
            self._discover_tournaments()

            # 2. Fetch basic match list (no odds - lightweight)
            raw = self.client.send_basic_match_list_request()
            matches = parse_matches_response(raw)
            logger.info("[Discovery] Found %d matches from HKJC", len(matches))

            # 3. Load enabled watch rules
            rules = self.db.get_active_watch_rules()
            if not rules:
                logger.info("[Discovery] No active watch rules, skipping")
                return

            logger.info(
                "[Discovery] Evaluating %d active watch rules", len(rules)
            )

            # 4. Evaluate each rule against matches
            now = datetime.now(timezone.utc)
            jobs_scheduled = 0

            for rule in rules:
                matched = filter_matches_by_rule(matches, rule)
                if not matched:
                    continue

                logger.info(
                    "[Discovery] Rule '%s' matched %d matches",
                    rule.name,
                    len(matched),
                )

                for match in matched:
                    for obs in rule.observations:
                        jobs_scheduled += self._schedule_observation(
                            match, obs, now
                        )

            logger.info(
                "[Discovery] Cycle complete: %d new jobs scheduled",
                jobs_scheduled,
            )

        except Exception:
            logger.exception("[Discovery] Error during discovery cycle")

    def _discover_tournaments(self):
        """Fetch and upsert tournament list from API."""
        try:
            response = self.client.send_tournament_list_request()
            tournaments = response.get("data", {}).get("tournamentList", [])
            if tournaments:
                result = self.db.upsert_tournaments(tournaments)
                if result["inserted"] > 0:
                    logger.info(
                        "[Discovery] Tournaments: %d new, %d updated",
                        result["inserted"],
                        result["updated"],
                    )
        except Exception:
            logger.exception("[Discovery] Failed to fetch tournament list")

    # ========================================================================
    # Layer 1 -> Layer 2: Schedule observations
    # ========================================================================

    def _schedule_observation(
        self, match: Match, obs: Observation, now: datetime
    ) -> int:
        """Schedule fetch jobs for a (match, observation) pair.

        Returns number of new jobs scheduled.
        """
        try:
            kickoff = parse_kickoff_time(match.kickOffTime)
        except (ValueError, TypeError):
            logger.warning(
                "Cannot parse kickoff time for %s: %s",
                match.frontEndId,
                match.kickOffTime,
            )
            return 0

        odds_key = ",".join(sorted(obs.odds_types))
        scheduled = 0

        if obs.schedule.mode == "event":
            for trigger in obs.schedule.triggers:
                trigger_time = compute_trigger_time(
                    kickoff, trigger.event, trigger.minutes
                )
                if trigger_time is None:
                    continue

                # Skip if trigger time is in the past
                if trigger_time <= now:
                    continue

                # Dedup key
                dedup_key = (
                    f"{match.id}:{odds_key}:{trigger_time.isoformat()}"
                )
                if dedup_key in self._scheduled_keys:
                    continue

                job_id = (
                    f"fetch:{match.frontEndId}:{odds_key}:{trigger.event}"
                )
                self._scheduler.add_job(
                    self.execute_fetch,
                    trigger=DateTrigger(run_date=trigger_time),
                    id=job_id,
                    name=(
                        f"Fetch {odds_key} for {match.frontEndId}"
                        f" ({trigger.event})"
                    ),
                    replace_existing=True,
                    kwargs={
                        "match_id": match.id,
                        "front_end_id": match.frontEndId,
                        "odds_types": obs.odds_types,
                    },
                )
                self._scheduled_keys.add(dedup_key)
                scheduled += 1

                logger.info(
                    "[Scheduler] Scheduled %s fetch for %s at %s (%s)",
                    odds_key,
                    match.frontEndId,
                    trigger_time.strftime("%Y-%m-%d %H:%M"),
                    trigger.event,
                )

        elif obs.schedule.mode == "continuous":
            start_time = compute_event_boundary(
                kickoff, obs.schedule.start_event
            )
            end_time = compute_event_boundary(
                kickoff, obs.schedule.end_event
            )
            interval = obs.schedule.interval_seconds or 300

            if start_time is None or end_time is None:
                return 0

            # Adjust start if it's in the past (start now instead)
            effective_start = max(start_time, now)

            # Skip if the window has already ended
            if end_time <= now:
                return 0

            dedup_key = (
                f"{match.id}:{odds_key}:continuous"
                f":{start_time.isoformat()}"
            )
            if dedup_key in self._scheduled_keys:
                return 0

            job_id = f"fetch:{match.frontEndId}:{odds_key}:continuous"
            self._scheduler.add_job(
                self.execute_fetch,
                trigger=IntervalTrigger(
                    seconds=interval,
                    start_date=effective_start,
                    end_date=end_time,
                ),
                id=job_id,
                name=(
                    f"Fetch {odds_key} for {match.frontEndId}"
                    f" (continuous {interval}s)"
                ),
                replace_existing=True,
                kwargs={
                    "match_id": match.id,
                    "front_end_id": match.frontEndId,
                    "odds_types": obs.odds_types,
                },
            )
            self._scheduled_keys.add(dedup_key)
            scheduled += 1

            logger.info(
                "[Scheduler] Scheduled %s continuous for %s"
                " every %ds (%s to %s)",
                odds_key,
                match.frontEndId,
                interval,
                effective_start.strftime("%H:%M"),
                end_time.strftime("%H:%M"),
            )

        return scheduled

    # ========================================================================
    # Layer 2: Fetch execution
    # ========================================================================

    def execute_fetch(
        self,
        match_id: str,
        front_end_id: str,
        odds_types: list[str],
    ):
        """Execute a fetch job: call API, parse, save to DB.

        Args:
            match_id: Internal match ID
            front_end_id: Display match ID (e.g., FB4342)
            odds_types: Odds type codes to fetch
        """
        logger.info(
            "[Fetch] Fetching %s for %s (id=%s)",
            ",".join(odds_types),
            front_end_id,
            match_id,
        )

        try:
            raw = self.client.send_detailed_match_list_request(
                odds_types=odds_types,
            )

            matches = parse_matches_response(raw)

            # Find our specific match
            target = None
            for m in matches:
                if m.id == match_id:
                    target = m
                    break

            if target is None:
                logger.warning(
                    "[Fetch] Match %s not found in API response"
                    " (%d matches returned)",
                    front_end_id,
                    len(matches),
                )
                return

            result = self.db.save_matches([target])
            logger.info(
                "[Fetch] Saved %s: %d match, %d odds snapshots",
                front_end_id,
                result["matches_upserted"],
                result["odds_snapshots"],
            )

        except Exception:
            logger.exception("[Fetch] Error fetching %s", front_end_id)

    # ========================================================================
    # One-shot mode
    # ========================================================================

    def run_once(self):
        """Single discovery + fetch cycle, then exit.

        Discovers matches, evaluates rules, fetches matching odds immediately,
        saves to DB.
        """
        logger.info("[Once] Running single fetch cycle...")

        try:
            # Refresh tournaments
            self._discover_tournaments()

            # Fetch all matches (no odds - lightweight)
            raw = self.client.send_basic_match_list_request()
            matches = parse_matches_response(raw)
            logger.info("[Once] Found %d matches from HKJC", len(matches))

            # Load rules
            rules = self.db.get_active_watch_rules()
            if not rules:
                logger.info("[Once] No active watch rules")
                return

            # Collect all needed odds types and matched match IDs
            all_odds_types: set[str] = set()
            matched_match_ids: set[str] = set()

            for rule in rules:
                matched = filter_matches_by_rule(matches, rule)
                if matched:
                    logger.info(
                        "[Once] Rule '%s' matched %d matches",
                        rule.name,
                        len(matched),
                    )
                    for m in matched:
                        matched_match_ids.add(m.id)
                    for obs in rule.observations:
                        all_odds_types.update(obs.odds_types)

            if not matched_match_ids:
                logger.info("[Once] No matches matched any rules")
                return

            logger.info(
                "[Once] Fetching odds [%s] for %d matched matches...",
                ",".join(sorted(all_odds_types)),
                len(matched_match_ids),
            )

            # Fetch with odds
            raw = self.client.fetch_matches_for_odds(
                odds_types=list(all_odds_types),
                with_preflight=True,
            )
            all_matches = parse_matches_response(raw)

            # Filter to matched matches only
            target_matches = [
                m for m in all_matches if m.id in matched_match_ids
            ]

            # Save
            result = self.db.save_matches(target_matches)
            logger.info(
                "[Once] Complete: saved %d matches, %d odds snapshots",
                result["matches_upserted"],
                result["odds_snapshots"],
            )

        except Exception:
            logger.exception("[Once] Error during single fetch cycle")
