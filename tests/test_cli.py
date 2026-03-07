"""Unit tests for cli.py using mongomock (no real MongoDB required)."""

import pytest

from hkjc_scrapper.cli import parse_observation, cmd_add_rule, cmd_list_rules, cmd_show_rule, cmd_enable_rule, cmd_disable_rule, cmd_delete_rule


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
