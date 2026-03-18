"""API response parser - transforms raw JSON into Pydantic models."""

from typing import Optional

from hkjc_scrapper.models import Match, WatchRule


def parse_matches_response(raw_json: dict) -> list[Match]:
    """
    Parse raw API response into Match models.

    Args:
        raw_json: Raw JSON response from HKJC API

    Returns:
        List of validated Match objects

    Raises:
        ValueError: If response structure is invalid
        pydantic.ValidationError: If match data doesn't match schema
    """
    if "data" not in raw_json:
        raise ValueError("Invalid response: missing 'data' field")

    if "matches" not in raw_json["data"]:
        raise ValueError("Invalid response: missing 'matches' field")

    matches_data = raw_json["data"]["matches"]

    if not isinstance(matches_data, list):
        raise ValueError("Invalid response: 'matches' must be a list")

    # Parse each match into a Pydantic model
    matches = [Match(**match_data) for match_data in matches_data]

    return matches


def filter_matches_by_rule(matches: list[Match], rule: WatchRule) -> list[Match]:
    """
    Filter matches that match a watch rule's criteria.

    Args:
        matches: List of Match objects
        rule: WatchRule to filter by

    Returns:
        List of matches that match the rule
    """
    filtered = []

    for match in matches:
        # Check if match matches any of the rule's filters
        match_found = False

        # Filter by specific match IDs
        if rule.match_filter.match_ids:
            if match.id in rule.match_filter.match_ids or match.frontEndId in rule.match_filter.match_ids:
                match_found = True

        # Filter by teams (check both home and away)
        if rule.match_filter.teams and not match_found:
            for team_name in rule.match_filter.teams:
                if (team_name.lower() in match.homeTeam.name_en.lower() or
                    team_name.lower() in match.awayTeam.name_en.lower() or
                    team_name.lower() in match.homeTeam.name_ch.lower() or
                    team_name.lower() in match.awayTeam.name_ch.lower()):
                    match_found = True
                    break

        # Filter by tournaments
        if rule.match_filter.tournaments and not match_found:
            if match.tournament.code in rule.match_filter.tournaments:
                match_found = True

        # If no filters specified, match all
        if (not rule.match_filter.match_ids and
            not rule.match_filter.teams and
            not rule.match_filter.tournaments):
            match_found = True

        if match_found:
            filtered.append(match)

    return filtered


def filter_fopools_by_odds_types(matches: list[Match], odds_types: list[str]) -> list[Match]:
    """
    Filter each match's foPools to only keep requested odds types.

    Args:
        matches: List of Match objects
        odds_types: List of odds type codes to keep (e.g., ["HAD", "CHL"])

    Returns:
        List of Match objects with filtered foPools
    """
    filtered_matches = []

    for match in matches:
        # Create a copy of the match with filtered foPools
        # We'll use model_copy to preserve all other data
        filtered_pools = [
            pool for pool in match.foPools
            if pool.oddsType in odds_types
        ]

        # Create new match with filtered pools
        match_dict = match.model_dump()
        match_dict["foPools"] = [pool.model_dump() for pool in filtered_pools]
        filtered_match = Match(**match_dict)

        filtered_matches.append(filtered_match)

    return filtered_matches


def get_match_description(match: Match) -> str:
    """
    Get a human-readable match description.

    Args:
        match: Match object

    Returns:
        String like "Manchester United vs Liverpool"
    """
    return f"{match.homeTeam.name_en} vs {match.awayTeam.name_en}"
