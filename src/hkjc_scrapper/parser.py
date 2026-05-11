"""API response parser - transforms raw JSON into Pydantic models."""

import json
import logging
from typing import Optional

from pydantic import ValidationError

from hkjc_scrapper.models import Match, WatchRule

logger = logging.getLogger(__name__)


def format_validation_errors(exc: ValidationError, limit: int = 5) -> str:
    """Format a pydantic ValidationError as a short human-readable string.

    Each error line: 'field.path: msg (got <input_type>)'
    """
    lines = []
    for err in exc.errors()[:limit]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "")
        input_val = err.get("input")
        input_type = type(input_val).__name__
        lines.append(f"{loc}: {msg} (got {input_type})")
    extra = len(exc.errors()) - limit
    if extra > 0:
        lines.append(f"... and {extra} more error(s)")
    return "\n".join(lines)


def parse_matches_response(raw_json: dict) -> list[Match]:
    """
    Parse raw API response into Match models.

    Malformed individual matches are logged and skipped — the cycle should
    not abort because one match has a contract violation.

    Args:
        raw_json: Raw JSON response from HKJC API

    Returns:
        List of validated Match objects

    Raises:
        ValueError: If response structure is invalid (missing data/matches keys)
    """
    if "data" not in raw_json:
        raise ValueError("Invalid response: missing 'data' field")

    if "matches" not in raw_json["data"]:
        raise ValueError("Invalid response: missing 'matches' field")

    matches_data = raw_json["data"]["matches"]

    if not isinstance(matches_data, list):
        raise ValueError("Invalid response: 'matches' must be a list")

    matches: list[Match] = []
    skipped = 0
    for match_data in matches_data:
        try:
            matches.append(Match(**match_data))
        except ValidationError as e:
            skipped += 1
            match_id = match_data.get("id") if isinstance(match_data, dict) else None
            feid = match_data.get("frontEndId") if isinstance(match_data, dict) else None
            logger.warning(
                "Skipping malformed match (id=%s frontEndId=%s):\n%s\npayload=%s",
                match_id,
                feid,
                format_validation_errors(e),
                json.dumps(match_data, default=str)[:1000],
            )

    if skipped:
        logger.warning(
            "parse_matches_response: skipped %d malformed match(es), %d ok",
            skipped, len(matches),
        )

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
