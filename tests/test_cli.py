"""Unit tests for cli.py using mongomock (no real MongoDB required)."""

from unittest.mock import MagicMock

import pytest

from hkjc_scrapper.cli import (
    cmd_add_rule,
    cmd_delete_rule,
    cmd_disable_rule,
    cmd_enable_rule,
    cmd_fetch_match,
    cmd_get_match,
    cmd_get_odds,
    cmd_list_matches,
    cmd_list_rules,
    cmd_show_rule,
    parse_observation,
)
from hkjc_scrapper.models import (
    Combination,
    FoPool,
    Line,
    Match,
    Selection,
    Team,
    Tournament,
)


# ============================================================================
# parse_observation tests
# ============================================================================

class TestParseObservation:
    """Tests for the observation string parser."""

    def test_event_mode_with_minutes(self):
        """Test parsing event mode with minutes."""
        obs = parse_observation("HAD,HHA,HDC:event:before_kickoff:30")
        assert obs.odds_types == ["HAD", "HHA", "HDC"]
        assert obs.schedule.mode == "event"
        assert len(obs.schedule.triggers) == 1
        assert obs.schedule.triggers[0].event == "before_kickoff"
        assert obs.schedule.triggers[0].minutes == 30

    def test_event_mode_without_minutes(self):
        """Test parsing event mode without minutes."""
        obs = parse_observation("CHL:event:at_kickoff")
        assert obs.odds_types == ["CHL"]
        assert obs.schedule.mode == "event"
        assert obs.schedule.triggers[0].event == "at_kickoff"
        assert obs.schedule.triggers[0].minutes is None

    def test_event_mode_at_halftime(self):
        """Test parsing at_halftime trigger."""
        obs = parse_observation("HAD:event:at_halftime")
        assert obs.schedule.triggers[0].event == "at_halftime"

    def test_continuous_mode(self):
        """Test parsing continuous mode."""
        obs = parse_observation("CHL:continuous:300:kickoff:fulltime")
        assert obs.odds_types == ["CHL"]
        assert obs.schedule.mode == "continuous"
        assert obs.schedule.interval_seconds == 300
        assert obs.schedule.start_event == "kickoff"
        assert obs.schedule.end_event == "fulltime"

    def test_invalid_format_too_few_parts(self):
        """Test that too few parts raises ValueError."""
        with pytest.raises(ValueError, match="Invalid observation format"):
            parse_observation("HAD")

    def test_invalid_event_mode_no_trigger(self):
        """Test that event mode without trigger raises ValueError."""
        with pytest.raises(ValueError, match="Event mode requires trigger"):
            parse_observation("HAD:event")

    def test_invalid_continuous_mode_missing_parts(self):
        """Test that continuous mode with missing parts raises ValueError."""
        with pytest.raises(ValueError, match="Continuous mode requires"):
            parse_observation("CHL:continuous:300")

    def test_invalid_mode(self):
        """Test that unknown mode raises ValueError."""
        with pytest.raises(ValueError, match="Unknown mode"):
            parse_observation("HAD:unknown:something")


# ============================================================================
# CLI command tests (using mongomock via mock_db fixture)
# ============================================================================

class _FakeArgs:
    """Fake argparse namespace for testing."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestCmdAddRule:
    """Tests for add-rule command."""

    def test_add_rule_success(self, mock_db):
        """Test successfully adding a rule."""
        args = _FakeArgs(
            name="Test Rule",
            teams="Manchester United",
            tournaments="EPL",
            match_ids="",
            observation=["HAD,HHA:event:before_kickoff:30"],
        )
        result = cmd_add_rule(args, mock_db)
        assert result == 0

        doc = mock_db.get_watch_rule("Test Rule")
        assert doc is not None
        assert doc["match_filter"]["teams"] == ["Manchester United"]

    def test_add_rule_continuous_observation(self, mock_db):
        """Test adding a rule with continuous observation."""
        args = _FakeArgs(
            name="Corner Watch",
            teams="",
            tournaments="LLG",
            match_ids="",
            observation=["CHL:continuous:300:kickoff:fulltime"],
        )
        result = cmd_add_rule(args, mock_db)
        assert result == 0

    def test_add_rule_multiple_observations(self, mock_db):
        """Test adding a rule with multiple observations."""
        args = _FakeArgs(
            name="Multi Obs",
            teams="",
            tournaments="EPL",
            match_ids="",
            observation=[
                "HAD,HHA:event:before_kickoff:30",
                "CHL:continuous:300:kickoff:fulltime",
            ],
        )
        result = cmd_add_rule(args, mock_db)
        assert result == 0

        doc = mock_db.get_watch_rule("Multi Obs")
        assert len(doc["observations"]) == 2

    def test_add_rule_duplicate_name(self, mock_db):
        """Test adding a rule with duplicate name fails."""
        args = _FakeArgs(
            name="Dup Rule",
            teams="",
            tournaments="EPL",
            match_ids="",
            observation=["HAD:event:at_kickoff"],
        )
        cmd_add_rule(args, mock_db)
        result = cmd_add_rule(args, mock_db)
        assert result == 1

    def test_add_rule_no_observations(self, mock_db):
        """Test adding a rule with no observations fails."""
        args = _FakeArgs(
            name="No Obs",
            teams="",
            tournaments="EPL",
            match_ids="",
            observation=[],
        )
        result = cmd_add_rule(args, mock_db)
        assert result == 1

    def test_add_rule_invalid_observation(self, mock_db):
        """Test adding a rule with invalid observation format fails."""
        args = _FakeArgs(
            name="Bad Obs",
            teams="",
            tournaments="EPL",
            match_ids="",
            observation=["INVALID"],
        )
        result = cmd_add_rule(args, mock_db)
        assert result == 1


class TestCmdListRules:
    """Tests for list-rules command."""

    def test_list_rules_empty(self, mock_db, capsys):
        """Test listing with no rules."""
        args = _FakeArgs()
        result = cmd_list_rules(args, mock_db)
        assert result == 0
        assert "No watch rules found" in capsys.readouterr().out

    def test_list_rules_with_rules(self, mock_db, sample_watch_rule, capsys):
        """Test listing rules shows table."""
        mock_db.add_watch_rule(sample_watch_rule)

        args = _FakeArgs()
        result = cmd_list_rules(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "Test EPL Rule" in output
        assert "ENABLED" in output


class TestCmdShowRule:
    """Tests for show-rule command."""

    def test_show_rule_found(self, mock_db, sample_watch_rule, capsys):
        """Test showing an existing rule."""
        mock_db.add_watch_rule(sample_watch_rule)

        args = _FakeArgs(name="Test EPL Rule")
        result = cmd_show_rule(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "Test EPL Rule" in output
        assert "Manchester United" in output

    def test_show_rule_not_found(self, mock_db, capsys):
        """Test showing a non-existent rule."""
        args = _FakeArgs(name="nonexistent")
        result = cmd_show_rule(args, mock_db)
        assert result == 1
        assert "not found" in capsys.readouterr().out


class TestCmdEnableDisableDelete:
    """Tests for enable, disable, delete commands."""

    def test_enable_disabled_rule(self, mock_db, sample_watch_rule, capsys):
        """Test enabling a disabled rule."""
        sample_watch_rule.enabled = False
        mock_db.add_watch_rule(sample_watch_rule)

        args = _FakeArgs(name="Test EPL Rule")
        result = cmd_enable_rule(args, mock_db)
        assert result == 0
        assert "Enabled" in capsys.readouterr().out

    def test_disable_enabled_rule(self, mock_db, sample_watch_rule, capsys):
        """Test disabling an enabled rule."""
        mock_db.add_watch_rule(sample_watch_rule)

        args = _FakeArgs(name="Test EPL Rule")
        result = cmd_disable_rule(args, mock_db)
        assert result == 0
        assert "Disabled" in capsys.readouterr().out

    def test_delete_rule(self, mock_db, sample_watch_rule, capsys):
        """Test deleting a rule."""
        mock_db.add_watch_rule(sample_watch_rule)

        args = _FakeArgs(name="Test EPL Rule")
        result = cmd_delete_rule(args, mock_db)
        assert result == 0
        assert "Deleted" in capsys.readouterr().out

    def test_enable_nonexistent(self, mock_db, capsys):
        """Test enabling a non-existent rule."""
        args = _FakeArgs(name="nonexistent")
        result = cmd_enable_rule(args, mock_db)
        assert result == 1

    def test_disable_nonexistent(self, mock_db, capsys):
        """Test disabling a non-existent rule."""
        args = _FakeArgs(name="nonexistent")
        result = cmd_disable_rule(args, mock_db)
        assert result == 1

    def test_delete_nonexistent(self, mock_db, capsys):
        """Test deleting a non-existent rule."""
        args = _FakeArgs(name="nonexistent")
        result = cmd_delete_rule(args, mock_db)
        assert result == 1


# ============================================================================
# list-matches / fetch-match tests
# ============================================================================

def _make_api_response(matches_data: list[dict]) -> dict:
    """Wrap match dicts in the API response envelope."""
    return {"data": {"matches": matches_data}}


def _sample_match_dict(
    match_id="50001111",
    front_end_id="FB9999",
    tournament_code="EPL",
    home="Team A",
    away="Team B",
    status="SCHEDULED",
):
    """Create a raw match dict as the API would return."""
    return {
        "id": match_id,
        "frontEndId": front_end_id,
        "matchDate": "2026-03-10+08:00",
        "kickOffTime": "2026-03-10T20:00:00.000+08:00",
        "status": status,
        "updateAt": "2026-03-10T10:00:00.000+08:00",
        "homeTeam": {"id": "T1", "name_en": home, "name_ch": "A隊"},
        "awayTeam": {"id": "T2", "name_en": away, "name_ch": "B隊"},
        "tournament": {
            "id": "TN1",
            "code": tournament_code,
            "name_en": f"League {tournament_code}",
            "name_ch": "聯賽",
        },
        "foPools": [],
    }


def _sample_match_dict_with_odds(match_id="50001111", front_end_id="FB9999"):
    """Create a raw match dict with HAD odds."""
    d = _sample_match_dict(match_id=match_id, front_end_id=front_end_id)
    d["foPools"] = [
        {
            "id": "P001",
            "status": "SELLINGSTARTED",
            "oddsType": "HAD",
            "instNo": 0,
            "inplay": False,
            "name_ch": "",
            "name_en": "",
            "updateAt": "2026-03-10T10:00:00.000+08:00",
            "expectedSuspendDateTime": "",
            "lines": [
                {
                    "lineId": "L001",
                    "status": "SELLINGSTARTED",
                    "condition": None,
                    "main": True,
                    "combinations": [
                        {
                            "combId": "C1",
                            "str": "H",
                            "status": "AVAILABLE",
                            "offerEarlySettlement": "N",
                            "currentOdds": "2.50",
                            "selections": [
                                {"selId": "S1", "str": "H", "name_en": "Home", "name_ch": "主"}
                            ],
                        },
                        {
                            "combId": "C2",
                            "str": "D",
                            "status": "AVAILABLE",
                            "offerEarlySettlement": "N",
                            "currentOdds": "3.20",
                            "selections": [
                                {"selId": "S2", "str": "D", "name_en": "Draw", "name_ch": "和"}
                            ],
                        },
                        {
                            "combId": "C3",
                            "str": "A",
                            "status": "AVAILABLE",
                            "offerEarlySettlement": "N",
                            "currentOdds": "2.80",
                            "selections": [
                                {"selId": "S3", "str": "A", "name_en": "Away", "name_ch": "客"}
                            ],
                        },
                    ],
                }
            ],
        }
    ]
    return d


class TestCmdListMatches:
    """Tests for list-matches command."""

    def test_list_matches_success(self, mock_db, capsys):
        """Test listing matches from a mocked API response."""
        mock_client = MagicMock()
        mock_client.send_basic_match_list_request.return_value = _make_api_response([
            _sample_match_dict("M1", "FB001", "EPL", "Liverpool", "Arsenal"),
            _sample_match_dict("M2", "FB002", "SFL", "Barcelona", "Real Madrid", "FIRSTHALF"),
        ])

        args = _FakeArgs(tournament="", status="", team="")
        result = cmd_list_matches(args, mock_db, mock_client)
        assert result == 0

        output = capsys.readouterr().out
        assert "Liverpool" in output
        assert "Barcelona" in output
        assert "2 matches displayed" in output

    def test_list_matches_filter_tournament(self, mock_db, capsys):
        """Test filtering by tournament code."""
        mock_client = MagicMock()
        mock_client.send_basic_match_list_request.return_value = _make_api_response([
            _sample_match_dict("M1", "FB001", "EPL", "Liverpool", "Arsenal"),
            _sample_match_dict("M2", "FB002", "SFL", "Barcelona", "Real Madrid"),
        ])

        args = _FakeArgs(tournament="SFL", status="", team="")
        result = cmd_list_matches(args, mock_db, mock_client)
        assert result == 0

        output = capsys.readouterr().out
        assert "Barcelona" in output
        assert "Liverpool" not in output
        assert "1 matches displayed" in output

    def test_list_matches_filter_status(self, mock_db, capsys):
        """Test filtering by match status."""
        mock_client = MagicMock()
        mock_client.send_basic_match_list_request.return_value = _make_api_response([
            _sample_match_dict("M1", "FB001", "EPL", "Liverpool", "Arsenal", "SCHEDULED"),
            _sample_match_dict("M2", "FB002", "EPL", "Chelsea", "Spurs", "FIRSTHALF"),
        ])

        args = _FakeArgs(tournament="", status="FIRSTHALF", team="")
        result = cmd_list_matches(args, mock_db, mock_client)
        assert result == 0

        output = capsys.readouterr().out
        assert "Chelsea" in output
        assert "Liverpool" not in output

    def test_list_matches_filter_team(self, mock_db, capsys):
        """Test filtering by team name (partial match)."""
        mock_client = MagicMock()
        mock_client.send_basic_match_list_request.return_value = _make_api_response([
            _sample_match_dict("M1", "FB001", "EPL", "Liverpool", "Arsenal"),
            _sample_match_dict("M2", "FB002", "EPL", "Chelsea", "Spurs"),
        ])

        args = _FakeArgs(tournament="", status="", team="arsenal")
        result = cmd_list_matches(args, mock_db, mock_client)
        assert result == 0

        output = capsys.readouterr().out
        assert "Arsenal" in output
        assert "Chelsea" not in output

    def test_list_matches_no_results(self, mock_db, capsys):
        """Test when no matches are returned."""
        mock_client = MagicMock()
        mock_client.send_basic_match_list_request.return_value = _make_api_response([])

        args = _FakeArgs(tournament="", status="", team="")
        result = cmd_list_matches(args, mock_db, mock_client)
        assert result == 0
        assert "No matches found" in capsys.readouterr().out


class TestCmdFetchMatch:
    """Tests for fetch-match command."""

    def test_fetch_by_id_and_save(self, mock_db, capsys):
        """Test fetching a match by ID and saving to DB."""
        mock_client = MagicMock()
        mock_client.fetch_matches_for_odds.return_value = _make_api_response([
            _sample_match_dict_with_odds("M1", "FB001"),
        ])

        args = _FakeArgs(id="M1", front_end_id="", odds="HAD", no_save=False)
        result = cmd_fetch_match(args, mock_db, mock_client)
        assert result == 0

        output = capsys.readouterr().out
        assert "FB001" in output
        assert "HAD" in output
        assert "H=2.50" in output
        assert "Saved to DB" in output

    def test_fetch_by_front_end_id(self, mock_db, capsys):
        """Test fetching a match by front-end ID."""
        mock_client = MagicMock()
        mock_client.fetch_matches_for_odds.return_value = _make_api_response([
            _sample_match_dict_with_odds("M1", "FB001"),
        ])

        args = _FakeArgs(id="", front_end_id="FB001", odds="HAD", no_save=False)
        result = cmd_fetch_match(args, mock_db, mock_client)
        assert result == 0

        output = capsys.readouterr().out
        assert "FB001" in output

    def test_fetch_no_save(self, mock_db, capsys):
        """Test --no-save flag shows data without saving."""
        mock_client = MagicMock()
        mock_client.fetch_matches_for_odds.return_value = _make_api_response([
            _sample_match_dict_with_odds("M1", "FB001"),
        ])

        args = _FakeArgs(id="M1", front_end_id="", odds="HAD", no_save=True)
        result = cmd_fetch_match(args, mock_db, mock_client)
        assert result == 0

        output = capsys.readouterr().out
        assert "--no-save" in output
        assert "Saved to DB" not in output

    def test_fetch_match_not_found(self, mock_db, capsys):
        """Test when target match is not in API response."""
        mock_client = MagicMock()
        mock_client.fetch_matches_for_odds.return_value = _make_api_response([
            _sample_match_dict("M99", "FB999"),
        ])

        args = _FakeArgs(id="M1", front_end_id="", odds="HAD", no_save=False)
        result = cmd_fetch_match(args, mock_db, mock_client)
        assert result == 1
        assert "not found" in capsys.readouterr().out

    def test_fetch_no_id_provided(self, mock_db, capsys):
        """Test error when neither --id nor --front-end-id is given."""
        mock_client = MagicMock()
        args = _FakeArgs(id="", front_end_id="", odds="HAD", no_save=False)
        result = cmd_fetch_match(args, mock_db, mock_client)
        assert result == 1

    def test_fetch_no_odds_provided(self, mock_db, capsys):
        """Test error when --odds is not provided."""
        mock_client = MagicMock()
        args = _FakeArgs(id="M1", front_end_id="", odds="", no_save=False)
        result = cmd_fetch_match(args, mock_db, mock_client)
        assert result == 1


# ============================================================================
# get-match / get-odds tests (DB query commands)
# ============================================================================

class TestCmdGetMatch:
    """Tests for get-match command (reads from DB)."""

    def test_get_match_by_id(self, mock_db, sample_match, capsys):
        """Test looking up a stored match by ID."""
        mock_db.upsert_match(sample_match)

        args = _FakeArgs(id=sample_match.id, front_end_id="", team="", tournament="")
        result = cmd_get_match(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "Manchester United" in output
        assert "Liverpool" in output
        assert "FB9999" in output

    def test_get_match_by_front_end_id(self, mock_db, sample_match, capsys):
        """Test looking up a stored match by front-end ID."""
        mock_db.upsert_match(sample_match)

        args = _FakeArgs(id="", front_end_id="FB9999", team="", tournament="")
        result = cmd_get_match(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "Manchester United" in output

    def test_get_match_by_team_search(self, mock_db, sample_match, capsys):
        """Test searching stored matches by team name."""
        mock_db.upsert_match(sample_match)

        args = _FakeArgs(id="", front_end_id="", team="manchester", tournament="")
        result = cmd_get_match(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "Manchester United" in output

    def test_get_match_by_tournament(self, mock_db, sample_match, capsys):
        """Test searching stored matches by tournament."""
        mock_db.upsert_match(sample_match)

        args = _FakeArgs(id="", front_end_id="", team="", tournament="EPL")
        result = cmd_get_match(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "EPL" in output

    def test_get_match_not_found(self, mock_db, capsys):
        """Test when match is not in DB."""
        args = _FakeArgs(id="nonexistent", front_end_id="", team="", tournament="")
        result = cmd_get_match(args, mock_db)
        assert result == 1
        assert "not found" in capsys.readouterr().out

    def test_get_match_no_args(self, mock_db, capsys):
        """Test error when no search criteria given."""
        args = _FakeArgs(id="", front_end_id="", team="", tournament="")
        result = cmd_get_match(args, mock_db)
        assert result == 1


class TestCmdGetOdds:
    """Tests for get-odds command (reads odds history from DB)."""

    def _seed_odds(self, mock_db, match_id="M1", odds_type="HAD", count=3):
        """Seed some odds history records."""
        from datetime import datetime, timedelta, timezone

        # Also seed the match in matches_current
        mock_db.matches_current.replace_one(
            {"_id": match_id},
            {
                "_id": match_id,
                "id": match_id,
                "frontEndId": "FB001",
                "kickOffTime": "2026-03-10T20:00:00.000+08:00",
                "homeTeam": {"name_en": "Team A"},
                "awayTeam": {"name_en": "Team B"},
                "tournament": {"code": "EPL", "name_en": "Eng Premier"},
                "status": "SCHEDULED",
            },
            upsert=True,
        )
        for i in range(count):
            mock_db.odds_history.insert_one({
                "matchId": match_id,
                "matchDescription": "Team A vs Team B",
                "oddsType": odds_type,
                "inplay": i >= 2,
                "lines": [{
                    "lineId": "L1",
                    "status": "SELLINGSTARTED",
                    "condition": None,
                    "main": True,
                    "combinations": [{
                        "combId": "C1", "str": "H",
                        "currentOdds": f"{2.50 + i * 0.1:.2f}",
                        "status": "AVAILABLE",
                    }],
                }],
                "fetchedAt": datetime(2026, 3, 10, 10 + i, 0, 0, tzinfo=timezone.utc),
            })

    def test_get_odds_latest(self, mock_db, capsys):
        """Test default mode (latest snapshot per type)."""
        self._seed_odds(mock_db, "M1", "HAD", 3)
        self._seed_odds(mock_db, "M1", "CHL", 2)

        args = _FakeArgs(
            id="M1", front_end_id="", odds="",
            latest=True, before_kickoff=False, all=False, last=0,
        )
        result = cmd_get_odds(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "Latest snapshot" in output
        assert "HAD" in output
        assert "CHL" in output

    def test_get_odds_filter_by_type(self, mock_db, capsys):
        """Test filtering by odds type."""
        self._seed_odds(mock_db, "M1", "HAD", 3)
        self._seed_odds(mock_db, "M1", "CHL", 2)

        args = _FakeArgs(
            id="M1", front_end_id="", odds="HAD",
            latest=True, before_kickoff=False, all=False, last=0,
        )
        result = cmd_get_odds(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "HAD" in output

    def test_get_odds_all_mode(self, mock_db, capsys):
        """Test --all mode shows all snapshots."""
        self._seed_odds(mock_db, "M1", "HAD", 3)

        args = _FakeArgs(
            id="M1", front_end_id="", odds="HAD",
            latest=False, before_kickoff=False, all=True, last=0,
        )
        result = cmd_get_odds(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "All snapshots (3 records)" in output

    def test_get_odds_last_n(self, mock_db, capsys):
        """Test --last N shows last N snapshots."""
        self._seed_odds(mock_db, "M1", "HAD", 5)

        args = _FakeArgs(
            id="M1", front_end_id="", odds="HAD",
            latest=False, before_kickoff=False, all=False, last=2,
        )
        result = cmd_get_odds(args, mock_db)
        assert result == 0

        output = capsys.readouterr().out
        assert "Last 2 snapshot" in output

    def test_get_odds_no_history(self, mock_db, capsys):
        """Test when match has no odds history."""
        mock_db.matches_current.replace_one(
            {"_id": "M1"},
            {"_id": "M1", "frontEndId": "FB001", "kickOffTime": "2026-03-10T20:00:00.000+08:00",
             "homeTeam": {"name_en": "A"}, "awayTeam": {"name_en": "B"},
             "tournament": {"code": "EPL"}, "status": "SCHEDULED"},
            upsert=True,
        )
        args = _FakeArgs(
            id="M1", front_end_id="", odds="",
            latest=True, before_kickoff=False, all=False, last=0,
        )
        result = cmd_get_odds(args, mock_db)
        assert result == 0
        assert "No odds history" in capsys.readouterr().out

    def test_get_odds_by_front_end_id(self, mock_db, capsys):
        """Test resolving match by front-end ID."""
        self._seed_odds(mock_db, "M1", "HAD", 1)

        args = _FakeArgs(
            id="", front_end_id="FB001", odds="",
            latest=True, before_kickoff=False, all=False, last=0,
        )
        result = cmd_get_odds(args, mock_db)
        assert result == 0

    def test_get_odds_no_id(self, mock_db, capsys):
        """Test error when no ID provided."""
        args = _FakeArgs(
            id="", front_end_id="", odds="",
            latest=True, before_kickoff=False, all=False, last=0,
        )
        result = cmd_get_odds(args, mock_db)
        assert result == 1
