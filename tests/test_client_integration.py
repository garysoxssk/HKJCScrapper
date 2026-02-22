"""Integration tests for client.py - actually calls HKJC API.

These tests are marked with @pytest.mark.integration and skipped by default.

Run with: pytest -m integration
Or skip with: pytest -m "not integration"
"""

import pytest

from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.config import Settings
from hkjc_scrapper.parser import parse_matches_response


@pytest.mark.integration
def test_fetch_basic_match_list():
    """Test fetching basic match list from live API."""
    client = HKJCGraphQLClient(Settings())

    response = client.send_basic_match_list_request()

    assert "data" in response
    assert "matches" in response["data"]
    assert isinstance(response["data"]["matches"], list)

    print(f"\nFetched {len(response['data']['matches'])} matches (basic)")


@pytest.mark.integration
def test_fetch_detailed_match_list_with_odds():
    """Test fetching detailed match list with odds from live API."""
    client = HKJCGraphQLClient(Settings())

    # Fetch HAD and CHL odds
    response = client.send_detailed_match_list_request(
        odds_types=["HAD", "CHL"]
    )

    assert "data" in response
    assert "matches" in response["data"]

    matches = response["data"]["matches"]
    assert isinstance(matches, list)

    if matches:
        # Check first match has odds
        first_match = matches[0]
        print(f"\nMatch {first_match.get('frontEndId')}: {first_match['homeTeam']['name_en']} vs {first_match['awayTeam']['name_en']}")
        print(f"FoPools: {len(first_match.get('foPools', []))}")

        # Verify foPools exist
        if first_match.get("foPools"):
            odds_types = [pool["oddsType"] for pool in first_match["foPools"]]
            print(f"Odds types: {odds_types}")


@pytest.mark.integration
def test_fetch_and_parse_integration():
    """End-to-end test: fetch from API and parse into models."""
    client = HKJCGraphQLClient(Settings())

    # Fetch with specific odds types
    response = client.fetch_matches_for_odds(
        odds_types=["HAD", "HHA", "CHL"],
        with_preflight=True
    )

    # Parse into Pydantic models
    matches = parse_matches_response(response)

    assert len(matches) > 0
    assert all(hasattr(m, "frontEndId") for m in matches)

    print(f"\nSuccessfully parsed {len(matches)} matches from live API")
    for match in matches[:3]:
        print(f"  {match.frontEndId}: {match.homeTeam.name_en} vs {match.awayTeam.name_en} [{match.status}]")
        print(f"    Odds types: {[p.oddsType for p in match.foPools]}")


@pytest.mark.integration
def test_options_preflight():
    """Test OPTIONS preflight request."""
    client = HKJCGraphQLClient(Settings())

    response = client.send_options_preflight()

    # OPTIONS should return 2xx status
    assert response.status_code in [200, 204]
