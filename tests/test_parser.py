"""Unit tests for parser.py."""

import pytest

from hkjc_scrapper.models import Match, WatchRule, MatchFilter, Observation, Schedule, ScheduleTrigger
from hkjc_scrapper.parser import (
    parse_matches_response,
    filter_matches_by_rule,
    filter_fopools_by_odds_types,
    get_match_description,
)


def test_parse_matches_response_success(sample_response_data):
    """Test successful parsing of sample response."""
    matches = parse_matches_response(sample_response_data)

    assert len(matches) == 1
    assert isinstance(matches[0], Match)
    assert matches[0].frontEndId == "FB4342"
    assert matches[0].homeTeam.name_en == "San Diego FC"
    assert matches[0].awayTeam.name_en == "CF Montreal"
    assert matches[0].tournament.code == "MLS"
    assert matches[0].status == "SECONDHALF"


def test_parse_matches_response_missing_data():
    """Test error handling for missing 'data' field."""
    with pytest.raises(ValueError, match="missing 'data' field"):
        parse_matches_response({"error": "something"})


def test_parse_matches_response_missing_matches():
    """Test error handling for missing 'matches' field."""
    with pytest.raises(ValueError, match="missing 'matches' field"):
        parse_matches_response({"data": {}})


def test_parse_matches_response_invalid_type():
    """Test error handling for non-list matches."""
    with pytest.raises(ValueError, match="'matches' must be a list"):
        parse_matches_response({"data": {"matches": "not a list"}})


def test_filter_matches_by_tournament(sample_matches):
    """Test filtering by tournament code."""
    rule = WatchRule(
        name="Test Rule",
        enabled=True,
        match_filter=MatchFilter(tournaments=["MLS"]),
        observations=[]
    )

    filtered = filter_matches_by_rule(sample_matches, rule)
    assert len(filtered) == 1
    assert filtered[0].tournament.code == "MLS"


def test_filter_matches_by_tournament_no_match(sample_matches):
    """Test filtering with non-matching tournament."""
    rule = WatchRule(
        name="Test Rule",
        enabled=True,
        match_filter=MatchFilter(tournaments=["EPL"]),  # Not in sample
        observations=[]
    )

    filtered = filter_matches_by_rule(sample_matches, rule)
    assert len(filtered) == 0


def test_filter_matches_by_team(sample_matches):
    """Test filtering by team name (case-insensitive, partial match)."""
    rule = WatchRule(
        name="Test Rule",
        enabled=True,
        match_filter=MatchFilter(teams=["San Diego"]),  # Partial match
        observations=[]
    )

    filtered = filter_matches_by_rule(sample_matches, rule)
    assert len(filtered) == 1
    assert "San Diego" in filtered[0].homeTeam.name_en


def test_filter_matches_by_match_id(sample_matches):
    """Test filtering by specific match ID."""
    rule = WatchRule(
        name="Test Rule",
        enabled=True,
        match_filter=MatchFilter(match_ids=["FB4342"]),
        observations=[]
    )

    filtered = filter_matches_by_rule(sample_matches, rule)
    assert len(filtered) == 1
    assert filtered[0].frontEndId == "FB4342"


def test_filter_matches_no_filters(sample_matches):
    """Test that no filters matches all."""
    rule = WatchRule(
        name="Test Rule",
        enabled=True,
        match_filter=MatchFilter(),  # Empty filters
        observations=[]
    )

    filtered = filter_matches_by_rule(sample_matches, rule)
    assert len(filtered) == len(sample_matches)


def test_filter_fopools_by_odds_types(sample_matches):
    """Test filtering odds pools by type."""
    # Sample has 8 odds types: HHA, HDC, HIL, CHL, CRS, TTG, NTS, CHD
    assert len(sample_matches[0].foPools) == 8

    # Filter to only HAD and CHL
    filtered = filter_fopools_by_odds_types(sample_matches, ["HHA", "CHL"])

    assert len(filtered) == 1
    assert len(filtered[0].foPools) == 2
    odds_types = [pool.oddsType for pool in filtered[0].foPools]
    assert set(odds_types) == {"HHA", "CHL"}


def test_filter_fopools_empty_list(sample_matches):
    """Test filtering with empty odds types list."""
    filtered = filter_fopools_by_odds_types(sample_matches, [])

    assert len(filtered) == 1
    assert len(filtered[0].foPools) == 0


def test_get_match_description(sample_matches):
    """Test match description generation."""
    desc = get_match_description(sample_matches[0])
    assert desc == "San Diego FC vs CF Montreal"
