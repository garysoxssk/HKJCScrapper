"""Unit tests for models.py."""

import pytest
from pydantic import ValidationError

from hkjc_scrapper.models import (
    Team, Tournament, Match, FoPool, Line, Combination, Selection,
    WatchRule, MatchFilter, Observation, Schedule, ScheduleTrigger,
    OddsType, TournamentCode, MatchStatus,
)


def test_team_model():
    """Test Team model validation."""
    team = Team(
        id="123",
        name_en="Manchester United",
        name_ch="曼聯"
    )
    assert team.name_en == "Manchester United"
    assert team.name_ch == "曼聯"


def test_tournament_model():
    """Test Tournament model with optional fields."""
    tournament = Tournament(
        id="456",
        frontEndId="EPL_2024",
        code="EPL",
        name_en="English Premier League",
        name_ch="英超"
    )
    assert tournament.code == "EPL"
    assert tournament.name_en == "English Premier League"


def test_match_model_from_sample(sample_response_data):
    """Test Match model with real sample data."""
    match_data = sample_response_data["data"]["matches"][0]
    match = Match(**match_data)

    assert match.frontEndId == "FB4342"
    assert match.status == "SECONDHALF"
    assert match.homeTeam.name_en == "San Diego FC"
    assert match.awayTeam.name_en == "CF Montreal"
    assert len(match.foPools) == 8


def test_match_model_missing_required_field():
    """Test that Match model raises error for missing required fields."""
    with pytest.raises(ValidationError):
        Match(
            id="123",
            # Missing frontEndId, matchDate, kickOffTime, status, etc.
        )


def test_watch_rule_model():
    """Test WatchRule model."""
    rule = WatchRule(
        name="Man Utd EPL",
        enabled=True,
        match_filter=MatchFilter(
            teams=["Manchester United"],
            tournaments=["EPL"]
        ),
        observations=[
            Observation(
                odds_types=["HAD", "HHA"],
                schedule=Schedule(
                    mode="event",
                    triggers=[
                        ScheduleTrigger(event="before_kickoff", minutes=30)
                    ]
                )
            )
        ]
    )

    assert rule.name == "Man Utd EPL"
    assert rule.enabled is True
    assert len(rule.match_filter.teams) == 1
    assert len(rule.observations) == 1
    assert rule.observations[0].schedule.mode == "event"


def test_watch_rule_continuous_schedule():
    """Test WatchRule with continuous schedule."""
    rule = WatchRule(
        name="La Liga Corners",
        enabled=True,
        match_filter=MatchFilter(tournaments=["LLG"]),
        observations=[
            Observation(
                odds_types=["CHL"],
                schedule=Schedule(
                    mode="continuous",
                    interval_seconds=300,
                    start_event="kickoff",
                    end_event="fulltime"
                )
            )
        ]
    )

    assert rule.observations[0].schedule.mode == "continuous"
    assert rule.observations[0].schedule.interval_seconds == 300
    assert rule.observations[0].schedule.start_event == "kickoff"


def test_odds_type_enum():
    """Test OddsType enum."""
    assert OddsType.HAD == "HAD"
    assert OddsType.CHL == "CHL"
    assert OddsType.HDC == "HDC"


def test_tournament_code_enum():
    """Test TournamentCode enum."""
    assert TournamentCode.EPL == "EPL"
    assert TournamentCode.LLG == "LLG"
    assert TournamentCode.MLS == "MLS"


def test_match_status_enum():
    """Test MatchStatus enum."""
    assert MatchStatus.SCHEDULED == "SCHEDULED"
    assert MatchStatus.FIRSTHALF == "FIRSTHALF"
    assert MatchStatus.FULLTIME == "FULLTIME"


def test_fopool_with_lines(sample_response_data):
    """Test FoPool parsing with lines and combinations."""
    match_data = sample_response_data["data"]["matches"][0]
    fopool_data = match_data["foPools"][0]  # HHA pool

    fopool = FoPool(**fopool_data)

    assert fopool.oddsType == "HHA"
    assert len(fopool.lines) > 0
    assert fopool.lines[0].main in [True, False]
    assert len(fopool.lines[0].combinations) > 0
    assert fopool.lines[0].combinations[0].currentOdds is not None
