"""Unit tests for tg_commands.py — TGCommandHandler and AddRuleWizard."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hkjc_scrapper.tg_commands import (
    AddRuleWizard,
    TGCommandHandler,
    _format_relative_to_kickoff,
    _format_rule_detail,
    _truncate,
    TG_MAX_LENGTH,
)


# ============================================================================
# Fixtures
# ============================================================================

def _make_settings(allowed_users: str = ""):
    from zoneinfo import ZoneInfo
    s = MagicMock()
    s.TG_COMMAND_ALLOWED_USERS = allowed_users
    s.tz = ZoneInfo("Asia/Hong_Kong")
    return s


def _make_handler(allowed_users: str = ""):
    """Create a TGCommandHandler with mocked dependencies."""
    tg_client = MagicMock()
    db = MagicMock()
    api = MagicMock()
    settings = _make_settings(allowed_users)
    return TGCommandHandler(tg_client, db, api, settings)


def _make_event(sender_id: int = 12345, text: str = ""):
    """Create a mock Telethon event."""
    event = MagicMock()
    event.sender_id = sender_id
    event.text = text
    event.reply = AsyncMock()
    event.answer = AsyncMock()
    event.edit = AsyncMock()
    return event


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ============================================================================
# _truncate helper
# ============================================================================

class TestTruncate:

    def test_short_text_unchanged(self):
        text = "Hello world"
        assert _truncate(text) == text

    def test_long_text_truncated(self):
        text = "x" * (TG_MAX_LENGTH + 100)
        result = _truncate(text)
        assert len(result) <= TG_MAX_LENGTH
        assert result.endswith("... (truncated)")

    def test_exactly_at_limit(self):
        text = "x" * TG_MAX_LENGTH
        result = _truncate(text)
        assert len(result) <= TG_MAX_LENGTH


# ============================================================================
# AddRuleWizard
# ============================================================================

class TestAddRuleWizard:

    def test_initial_state(self):
        wizard = AddRuleWizard()
        assert wizard.step == "tournaments"
        assert wizard.tournaments == []
        assert wizard.odds_types == []
        assert not wizard.is_timed_out()

    def test_not_timed_out_immediately(self):
        wizard = AddRuleWizard()
        assert not wizard.is_timed_out(timeout_seconds=300)

    def test_timed_out_after_expiry(self):
        wizard = AddRuleWizard()
        wizard.created_at = datetime.now() - timedelta(seconds=400)
        assert wizard.is_timed_out(timeout_seconds=300)

    def test_state_transitions(self):
        wizard = AddRuleWizard()
        wizard.tournaments = ["EPL"]
        wizard.odds_types = ["HAD"]
        wizard.schedule_mode = "event"
        wizard.step = "trigger_event"
        assert wizard.step == "trigger_event"
        assert wizard.schedule_mode == "event"

    def test_tournament_toggle(self):
        wizard = AddRuleWizard()
        wizard.tournaments.append("EPL")
        assert "EPL" in wizard.tournaments
        wizard.tournaments.remove("EPL")
        assert "EPL" not in wizard.tournaments


# ============================================================================
# TGCommandHandler._check_auth
# ============================================================================

class TestCheckAuth:

    def test_empty_allowed_users_allows_all(self):
        handler = _make_handler(allowed_users="")
        event = _make_event(sender_id=99999)
        result = _run(handler._check_auth(event))
        assert result is True
        event.reply.assert_not_called()

    def test_allowed_user_passes(self):
        handler = _make_handler(allowed_users="12345,67890")
        event = _make_event(sender_id=12345)
        result = _run(handler._check_auth(event))
        assert result is True

    def test_unauthorized_user_rejected(self):
        handler = _make_handler(allowed_users="12345")
        event = _make_event(sender_id=99999)
        result = _run(handler._check_auth(event))
        assert result is False
        event.reply.assert_called_once_with("Unauthorized.")

    def test_parse_allowed_users_handles_spaces(self):
        handler = _make_handler(allowed_users=" 12345 , 67890 ")
        assert 12345 in handler._allowed_users
        assert 67890 in handler._allowed_users

    def test_parse_allowed_users_skips_invalid(self):
        handler = _make_handler(allowed_users="12345,notanumber")
        assert 12345 in handler._allowed_users
        assert len(handler._allowed_users) == 1


# ============================================================================
# _cmd_help
# ============================================================================

class TestCmdHelp:

    def test_help_lists_all_commands(self):
        handler = _make_handler()
        event = _make_event()
        _run(handler._cmd_help(event))
        event.reply.assert_called_once()
        msg = event.reply.call_args[0][0]
        for cmd in ["/help", "/status", "/matches", "/fetch", "/odds",
                    "/rules", "/addrule", "/enablerule", "/disablerule", "/deleterule"]:
            assert cmd in msg

    def test_help_blocked_for_unauthorized(self):
        handler = _make_handler(allowed_users="99")
        event = _make_event(sender_id=12345)
        _run(handler._cmd_help(event))
        # Should only call reply once (Unauthorized), not twice
        assert event.reply.call_count == 1
        assert "Unauthorized" in event.reply.call_args[0][0]


# ============================================================================
# _cmd_status
# ============================================================================

class TestCmdStatus:

    def test_status_shows_active_rules_and_uptime(self):
        handler = _make_handler()
        handler.db.get_active_watch_rules.return_value = [MagicMock(), MagicMock()]
        event = _make_event()
        _run(handler._cmd_status(event))
        event.reply.assert_called_once()
        msg = event.reply.call_args[0][0]
        assert "Active rules: 2" in msg
        assert "Uptime" in msg


# ============================================================================
# _cmd_rules
# ============================================================================

class TestCmdRules:

    def test_rules_shows_buttons_for_each_rule(self):
        handler = _make_handler()
        handler.db.get_all_watch_rules.return_value = [
            {"name": "EPL HAD", "enabled": True},
            {"name": "La Liga CHL", "enabled": False},
        ]
        event = _make_event()
        _run(handler._cmd_rules(event))
        event.reply.assert_called_once()
        # Check buttons were generated (second positional or keyword arg)
        call_kwargs = event.reply.call_args
        buttons = call_kwargs[1].get("buttons") or call_kwargs[0][1]
        assert buttons is not None
        assert len(buttons) >= 2  # At least one row per rule

    def test_rules_no_rules_returns_message(self):
        handler = _make_handler()
        handler.db.get_all_watch_rules.return_value = []
        event = _make_event()
        _run(handler._cmd_rules(event))
        event.reply.assert_called_once()
        assert "No watch rules" in event.reply.call_args[0][0]

    def test_rules_message_contains_rule_names(self):
        handler = _make_handler()
        handler.db.get_all_watch_rules.return_value = [
            {"name": "My EPL Rule", "enabled": True},
        ]
        event = _make_event()
        _run(handler._cmd_rules(event))
        msg = event.reply.call_args[0][0]
        assert "My EPL Rule" in msg

    def test_rules_shows_rule_details(self):
        handler = _make_handler()
        handler.db.get_all_watch_rules.return_value = [
            {
                "name": "La Liga Big 3",
                "enabled": True,
                "match_filter": {
                    "teams": ["Barcelona", "Real Madrid"],
                    "tournaments": ["SFL"],
                },
                "observations": [
                    {
                        "odds_types": ["HAD", "HIL"],
                        "schedule": {
                            "mode": "event",
                            "triggers": [{"event": "before_kickoff", "minutes": 30}],
                        },
                    }
                ],
            }
        ]
        event = _make_event()
        _run(handler._cmd_rules(event))
        msg = event.reply.call_args[0][0]
        assert "Barcelona" in msg
        assert "SFL" in msg
        assert "HAD" in msg
        assert "before_kickoff" in msg

    def test_rules_buttons_have_index(self):
        handler = _make_handler()
        handler.db.get_all_watch_rules.return_value = [
            {"name": "Rule A", "enabled": True},
            {"name": "Rule B", "enabled": False},
        ]
        event = _make_event()
        _run(handler._cmd_rules(event))
        call_kwargs = event.reply.call_args
        buttons = call_kwargs[1].get("buttons") or call_kwargs[0][1]
        # First rule row should have "#1" in button text
        row0 = buttons[0]
        assert any("#1" in btn.text for btn in row0)
        # Second rule row should have "#2" in button text
        row1 = buttons[1]
        assert any("#2" in btn.text for btn in row1)
        # Message should also contain #1 and #2
        msg = event.reply.call_args[0][0]
        assert "#1" in msg
        assert "#2" in msg


# ============================================================================
# _cb_rules
# ============================================================================

class TestCbRules:

    def test_enable_rule(self):
        handler = _make_handler()
        handler.db.enable_watch_rule.return_value = True
        event = _make_event()
        event.data = b"r:enable:EPL HAD"
        _run(handler._cb_rules(event))
        handler.db.enable_watch_rule.assert_called_once_with("EPL HAD")
        event.edit.assert_called_once()
        assert "enabled" in event.edit.call_args[0][0].lower()

    def test_disable_rule(self):
        handler = _make_handler()
        handler.db.disable_watch_rule.return_value = True
        event = _make_event()
        event.data = b"r:disable:My Rule"
        _run(handler._cb_rules(event))
        handler.db.disable_watch_rule.assert_called_once_with("My Rule")
        assert "disabled" in event.edit.call_args[0][0].lower()

    def test_delete_rule_shows_confirmation(self):
        handler = _make_handler()
        event = _make_event()
        event.data = b"r:del:My Rule"
        _run(handler._cb_rules(event))
        # Should show confirmation prompt, not delete yet
        handler.db.delete_watch_rule.assert_not_called()
        event.edit.assert_called_once()
        call_kwargs = event.edit.call_args
        buttons = call_kwargs[1].get("buttons")
        assert buttons is not None

    def test_delete_rule_confirmed(self):
        handler = _make_handler()
        handler.db.delete_watch_rule.return_value = True
        event = _make_event()
        event.data = b"r:del:confirm:My Rule"
        _run(handler._cb_rules(event))
        handler.db.delete_watch_rule.assert_called_once_with("My Rule")
        assert "deleted" in event.edit.call_args[0][0].lower()

    def test_enable_not_found(self):
        handler = _make_handler()
        handler.db.enable_watch_rule.return_value = False
        event = _make_event()
        event.data = b"r:enable:Unknown"
        _run(handler._cb_rules(event))
        assert "not found" in event.edit.call_args[0][0].lower()

    def test_unauthorized_blocked(self):
        handler = _make_handler(allowed_users="99")
        event = _make_event(sender_id=12345)
        event.data = b"r:enable:Some Rule"
        _run(handler._cb_rules(event))
        handler.db.enable_watch_rule.assert_not_called()


# ============================================================================
# _cb_cancel
# ============================================================================

class TestCbCancel:

    def test_cancel_cleans_wizard(self):
        handler = _make_handler()
        user_id = 12345
        handler._addrule_wizards[user_id] = AddRuleWizard()
        event = _make_event(sender_id=user_id)
        _run(handler._cb_cancel(event))
        assert user_id not in handler._addrule_wizards
        event.edit.assert_called_once_with("Cancelled.")

    def test_cancel_no_wizard_ok(self):
        handler = _make_handler()
        event = _make_event(sender_id=12345)
        _run(handler._cb_cancel(event))
        event.edit.assert_called_once_with("Cancelled.")


# ============================================================================
# _cmd_addrule wizard flow
# ============================================================================

class TestAddruleWizard:

    def test_addrule_starts_wizard(self):
        handler = _make_handler()
        event = _make_event(sender_id=12345)
        _run(handler._cmd_addrule(event))
        assert 12345 in handler._addrule_wizards
        assert handler._addrule_wizards[12345].step == "tournaments"

    def test_addrule_creates_new_wizard_on_restart(self):
        handler = _make_handler()
        handler._addrule_wizards[12345] = AddRuleWizard()
        handler._addrule_wizards[12345].step = "confirming"
        event = _make_event(sender_id=12345)
        _run(handler._cmd_addrule(event))
        # Should reset to fresh wizard
        assert handler._addrule_wizards[12345].step == "tournaments"

    def test_wizard_tournament_toggle(self):
        handler = _make_handler()
        user_id = 12345
        handler._addrule_wizards[user_id] = AddRuleWizard()
        event = _make_event(sender_id=user_id)
        event.data = b"ar:t:EPL"
        _run(handler._cb_addrule(event))
        assert "EPL" in handler._addrule_wizards[user_id].tournaments

    def test_wizard_tournament_toggle_twice_removes(self):
        handler = _make_handler()
        user_id = 12345
        wizard = AddRuleWizard()
        wizard.tournaments = ["EPL"]
        handler._addrule_wizards[user_id] = wizard
        event = _make_event(sender_id=user_id)
        event.data = b"ar:t:EPL"
        _run(handler._cb_addrule(event))
        assert "EPL" not in handler._addrule_wizards[user_id].tournaments

    def test_wizard_next_advances_step(self):
        handler = _make_handler()
        user_id = 12345
        wizard = AddRuleWizard()
        wizard.tournaments = ["EPL"]
        handler._addrule_wizards[user_id] = wizard
        event = _make_event(sender_id=user_id)
        event.data = b"ar:next"
        _run(handler._cb_addrule(event))
        assert handler._addrule_wizards[user_id].step == "odds_types"

    def test_wizard_next_requires_tournament_selected(self):
        handler = _make_handler()
        user_id = 12345
        wizard = AddRuleWizard()
        wizard.tournaments = []  # nothing selected
        handler._addrule_wizards[user_id] = wizard
        event = _make_event(sender_id=user_id)
        event.data = b"ar:next"
        _run(handler._cb_addrule(event))
        # Should NOT advance
        assert handler._addrule_wizards[user_id].step == "tournaments"
        event.answer.assert_called()

    def test_wizard_schedule_mode_event(self):
        handler = _make_handler()
        user_id = 12345
        wizard = AddRuleWizard()
        wizard.step = "schedule_mode"
        handler._addrule_wizards[user_id] = wizard
        event = _make_event(sender_id=user_id)
        event.data = b"ar:s:event"
        _run(handler._cb_addrule(event))
        assert handler._addrule_wizards[user_id].schedule_mode == "event"
        assert handler._addrule_wizards[user_id].step == "trigger_event"

    def test_wizard_schedule_mode_continuous(self):
        handler = _make_handler()
        user_id = 12345
        wizard = AddRuleWizard()
        wizard.step = "schedule_mode"
        handler._addrule_wizards[user_id] = wizard
        event = _make_event(sender_id=user_id)
        event.data = b"ar:s:continuous"
        _run(handler._cb_addrule(event))
        assert handler._addrule_wizards[user_id].schedule_mode == "continuous"
        assert handler._addrule_wizards[user_id].step == "interval"

    def test_wizard_timed_out_cleans_up(self):
        handler = _make_handler()
        user_id = 12345
        wizard = AddRuleWizard()
        wizard.created_at = datetime.now() - timedelta(seconds=400)
        handler._addrule_wizards[user_id] = wizard
        event = _make_event(sender_id=user_id)
        event.data = b"ar:t:EPL"
        _run(handler._cb_addrule(event))
        assert user_id not in handler._addrule_wizards
        event.edit.assert_called_once()
        assert "timed out" in event.edit.call_args[0][0].lower()

    def test_wizard_no_session_handled(self):
        handler = _make_handler()
        event = _make_event(sender_id=12345)
        event.data = b"ar:t:EPL"
        _run(handler._cb_addrule(event))
        event.edit.assert_called_once()
        assert "expired" in event.edit.call_args[0][0].lower()


# ============================================================================
# register_handlers
# ============================================================================

# ============================================================================
# _format_relative_to_kickoff helper
# ============================================================================

class TestFormatRelativeToKickoff:

    def test_before_kickoff(self):
        fetched = datetime(2026, 3, 21, 19, 30, 0)
        result = _format_relative_to_kickoff(fetched, "2026-03-21T20:00:00")
        assert result == "30 min before kickoff"

    def test_after_kickoff(self):
        fetched = datetime(2026, 3, 21, 20, 45, 0)
        result = _format_relative_to_kickoff(fetched, "2026-03-21T20:00:00")
        assert result == "45 min after kickoff"

    def test_at_kickoff(self):
        fetched = datetime(2026, 3, 21, 20, 0, 0)
        result = _format_relative_to_kickoff(fetched, "2026-03-21T20:00:00")
        assert result == "at kickoff"

    def test_hours_before_kickoff(self):
        fetched = datetime(2026, 3, 21, 17, 0, 0)
        result = _format_relative_to_kickoff(fetched, "2026-03-21T20:00:00")
        assert "3 hours before kickoff" in result

    def test_invalid_kickoff_returns_none(self):
        fetched = datetime(2026, 3, 21, 20, 0, 0)
        result = _format_relative_to_kickoff(fetched, "not-a-date")
        assert result is None

    def test_none_kickoff_returns_none(self):
        fetched = datetime(2026, 3, 21, 20, 0, 0)
        result = _format_relative_to_kickoff(fetched, None)
        assert result is None


# ============================================================================
# _format_rule_detail helper
# ============================================================================

class TestFormatRuleDetail:

    def test_event_rule(self):
        rule = {
            "match_filter": {"teams": ["Barcelona"], "tournaments": ["SFL"]},
            "observations": [{
                "odds_types": ["HAD", "HHA"],
                "schedule": {
                    "mode": "event",
                    "triggers": [{"event": "before_kickoff", "minutes": 30}],
                },
            }],
        }
        result = _format_rule_detail(rule)
        assert "Barcelona" in result
        assert "SFL" in result
        assert "HAD" in result
        assert "before_kickoff" in result
        assert "30min" in result

    def test_continuous_rule(self):
        rule = {
            "match_filter": {"tournaments": ["EPL"]},
            "observations": [{
                "odds_types": ["CHL"],
                "schedule": {
                    "mode": "continuous",
                    "interval_seconds": 300,
                    "start_event": "kickoff",
                    "end_event": "fulltime",
                },
            }],
        }
        result = _format_rule_detail(rule)
        assert "EPL" in result
        assert "300s" in result
        assert "kickoff" in result
        assert "fulltime" in result

    def test_no_filters_shows_all_matches(self):
        rule = {
            "match_filter": {},
            "observations": [],
        }
        result = _format_rule_detail(rule)
        assert "all matches" in result


# ============================================================================
# _cmd_jobs — scheduled jobs viewer
# ============================================================================

class TestCmdJobs:

    def test_jobs_empty(self):
        handler = _make_handler()
        handler.db.get_all_scheduled_jobs.return_value = []
        event = _make_event(text="/jobs")
        _run(handler._cmd_jobs(event))
        msg = event.reply.call_args[0][0]
        assert "No scheduled jobs" in msg

    def test_jobs_shows_details(self):
        from datetime import timezone as tz
        handler = _make_handler()
        handler.db.get_all_scheduled_jobs.return_value = [
            {
                "front_end_id": "FB6755",
                "job_type": "continuous",
                "odds_types": ["CHL"],
                "interval_seconds": 300,
                "start_time": datetime(2026, 4, 7, 19, 0, tzinfo=tz.utc),
                "end_time": datetime(2026, 4, 7, 20, 45, tzinfo=tz.utc),
                "created_at": datetime(2026, 4, 6, 10, 0, tzinfo=tz.utc),
            },
            {
                "front_end_id": "FB4233",
                "job_type": "event",
                "odds_types": ["HAD", "HHA"],
                "trigger_time": datetime(2026, 4, 7, 11, 30, tzinfo=tz.utc),
                "created_at": datetime(2026, 4, 6, 10, 0, tzinfo=tz.utc),
            },
        ]
        event = _make_event(text="/jobs")
        _run(handler._cmd_jobs(event))
        msg = event.reply.call_args[0][0]
        assert "Scheduled Jobs (2)" in msg
        assert "FB6755" in msg
        assert "CHL" in msg
        assert "300s" in msg
        assert "FB4233" in msg
        assert "HAD" in msg

    def test_jobs_sorted_by_trigger_time(self):
        """Jobs should be sorted by trigger time ascending."""
        from datetime import timezone as tz
        handler = _make_handler()
        handler.db.get_all_scheduled_jobs.return_value = [
            {
                "front_end_id": "FB_LATER",
                "job_type": "event",
                "odds_types": ["HHA"],
                "trigger_time": datetime(2026, 4, 7, 18, 0, tzinfo=tz.utc),
                "created_at": datetime(2026, 4, 6, 10, 0, tzinfo=tz.utc),
            },
            {
                "front_end_id": "FB_EARLIER",
                "job_type": "event",
                "odds_types": ["HAD"],
                "trigger_time": datetime(2026, 4, 7, 12, 0, tzinfo=tz.utc),
                "created_at": datetime(2026, 4, 6, 10, 0, tzinfo=tz.utc),
            },
        ]
        event = _make_event(text="/jobs")
        _run(handler._cmd_jobs(event))
        msg = event.reply.call_args[0][0]
        # FB_EARLIER should appear before FB_LATER
        assert msg.index("FB_EARLIER") < msg.index("FB_LATER")


# ============================================================================
# _cb_fetch — odds details in response
# ============================================================================

class TestCbFetchOddsDetails:

    def test_fetch_shows_odds_details(self):
        handler = _make_handler()
        # Create mock match with foPools (Pydantic model attributes)
        combo_h = MagicMock()
        combo_h.str = "H"
        combo_h.currentOdds = "2.50"
        combo_d = MagicMock()
        combo_d.str = "D"
        combo_d.currentOdds = "3.20"
        combo_a = MagicMock()
        combo_a.str = "A"
        combo_a.currentOdds = "2.80"

        line = MagicMock()
        line.condition = None
        line.main = True
        line.combinations = [combo_h, combo_d, combo_a]

        pool = MagicMock()
        pool.oddsType = "HAD"
        pool.lines = [line]

        target = MagicMock()
        target.frontEndId = "FB4233"
        target.homeTeam.name_en = "Nottingham Forest"
        target.awayTeam.name_en = "Liverpool"
        target.foPools = [pool]

        with patch("hkjc_scrapper.parser.parse_matches_response", return_value=[target]):
            handler.api.fetch_matches_for_odds.return_value = {}
            handler.db.save_matches.return_value = {"odds_snapshots": 1}
            event = _make_event()
            event.data = b"f:FB4233:HAD"
            _run(handler._cb_fetch(event))
            msg = event.edit.call_args_list[-1][0][0]
            assert "H=2.50" in msg
            assert "D=3.20" in msg
            assert "A=2.80" in msg
            assert "(main)" in msg
            assert "Snapshots saved: 1" in msg


# ============================================================================
# _cb_odds — fetch time + relative time
# ============================================================================

class TestCbOddsFetchTime:

    def test_odds_shows_fetch_time(self):
        handler = _make_handler()
        fetched_at = datetime(2026, 3, 21, 14, 30, 0)
        match_doc = {
            "_id": "50062141",
            "frontEndId": "FB4233",
            "kickOffTime": "2026-03-21T14:00:00",
        }
        handler.db.get_match_by_front_end_id.return_value = match_doc
        handler.db.get_latest_odds.return_value = [{
            "fetchedAt": fetched_at,
            "lines": [{
                "condition": None,
                "main": True,
                "combinations": [
                    {"str": "H", "currentOdds": "2.50"},
                    {"str": "D", "currentOdds": "3.20"},
                    {"str": "A", "currentOdds": "2.80"},
                ],
            }],
        }]
        event = _make_event()
        event.data = b"o:FB4233:HAD"
        _run(handler._cb_odds(event))
        msg = event.edit.call_args[0][0]
        assert "2026-03-21 14:30:00" in msg
        assert "30 min after kickoff" in msg

    def test_odds_shows_before_kickoff(self):
        handler = _make_handler()
        fetched_at = datetime(2026, 3, 21, 13, 30, 0)
        match_doc = {
            "_id": "50062141",
            "frontEndId": "FB4233",
            "kickOffTime": "2026-03-21T14:00:00",
        }
        handler.db.get_match_by_front_end_id.return_value = match_doc
        handler.db.get_latest_odds.return_value = [{
            "fetchedAt": fetched_at,
            "lines": [],
        }]
        event = _make_event()
        event.data = b"o:FB4233:HAD"
        _run(handler._cb_odds(event))
        msg = event.edit.call_args[0][0]
        assert "30 min before kickoff" in msg

    def test_odds_handles_missing_kickoff(self):
        handler = _make_handler()
        fetched_at = datetime(2026, 3, 21, 14, 30, 0)
        match_doc = {
            "_id": "50062141",
            "frontEndId": "FB4233",
            # No kickOffTime
        }
        handler.db.get_match_by_front_end_id.return_value = match_doc
        handler.db.get_latest_odds.return_value = [{
            "fetchedAt": fetched_at,
            "lines": [],
        }]
        event = _make_event()
        event.data = b"o:FB4233:HAD"
        _run(handler._cb_odds(event))
        msg = event.edit.call_args[0][0]
        # Should still show fetch time but no relative time
        assert "2026-03-21 14:30:00" in msg
        assert "kickoff" not in msg.lower()


# ============================================================================
# register_handlers
# ============================================================================

class TestRegisterHandlers:

    def test_register_handlers_calls_client_on(self):
        handler = _make_handler()
        handler.register_handlers()
        # client.on should have been called multiple times (once per handler)
        assert handler.client.on.call_count >= 10
