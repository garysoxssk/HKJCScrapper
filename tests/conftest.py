"""Pytest configuration and shared fixtures."""

import json
from pathlib import Path

import mongomock
import pytest

from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.models import (
    Combination,
    FoPool,
    Line,
    Match,
    MatchFilter,
    Observation,
    Schedule,
    ScheduleTrigger,
    Selection,
    Team,
    Tournament,
    WatchRule,
)


# ============================================================================
# Sample data fixtures
# ============================================================================

@pytest.fixture
def sample_response_data():
    """Load the sample API response JSON."""
    sample_path = Path(__file__).parent.parent / "docs" / "api" / "base_api_sample_response.json"
    with open(sample_path) as f:
        return json.load(f)


@pytest.fixture
def sample_matches(sample_response_data):
    """Parse sample response into Match objects."""
    from hkjc_scrapper.parser import parse_matches_response
    return parse_matches_response(sample_response_data)


@pytest.fixture
def sample_match():
    """Create a minimal Match object for testing."""
    return Match(
        id="50001111",
        frontEndId="FB9999",
        matchDate="2026-03-01+08:00",
        kickOffTime="2026-03-01T20:00:00.000+08:00",
        status="SCHEDULED",
        updateAt="2026-03-01T10:00:00.000+08:00",
        homeTeam=Team(id="T001", name_en="Manchester United", name_ch="曼聯"),
        awayTeam=Team(id="T002", name_en="Liverpool", name_ch="利物浦"),
        tournament=Tournament(
            id="TN001", code="EPL", name_en="Eng Premier", name_ch="英超"
        ),
        foPools=[
            FoPool(
                id="P001",
                status="SELLINGSTARTED",
                oddsType="HAD",
                updateAt="2026-03-01T10:00:00.000+08:00",
                lines=[
                    Line(
                        lineId="L001",
                        status="SELLINGSTARTED",
                        main=True,
                        combinations=[
                            Combination(
                                combId="C001",
                                str="H",
                                status="AVAILABLE",
                                offerEarlySettlement="N",
                                currentOdds="2.50",
                                selections=[
                                    Selection(
                                        selId="S001",
                                        str="H",
                                        name_en="Home",
                                        name_ch="主",
                                    )
                                ],
                            ),
                            Combination(
                                combId="C002",
                                str="D",
                                status="AVAILABLE",
                                offerEarlySettlement="N",
                                currentOdds="3.20",
                                selections=[
                                    Selection(
                                        selId="S002",
                                        str="D",
                                        name_en="Draw",
                                        name_ch="和",
                                    )
                                ],
                            ),
                            Combination(
                                combId="C003",
                                str="A",
                                status="AVAILABLE",
                                offerEarlySettlement="N",
                                currentOdds="2.80",
                                selections=[
                                    Selection(
                                        selId="S003",
                                        str="A",
                                        name_en="Away",
                                        name_ch="客",
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            )
        ],
    )


@pytest.fixture
def sample_watch_rule():
    """Create a sample WatchRule for testing."""
    return WatchRule(
        name="Test EPL Rule",
        enabled=True,
        match_filter=MatchFilter(
            teams=["Manchester United"],
            tournaments=["EPL"],
        ),
        observations=[
            Observation(
                odds_types=["HAD", "HHA", "HDC"],
                schedule=Schedule(
                    mode="event",
                    triggers=[
                        ScheduleTrigger(event="before_kickoff", minutes=30)
                    ],
                ),
            ),
            Observation(
                odds_types=["CHL"],
                schedule=Schedule(
                    mode="continuous",
                    interval_seconds=300,
                    start_event="kickoff",
                    end_event="fulltime",
                ),
            ),
        ],
    )


# ============================================================================
# MongoDB fixtures (mongomock for unit tests)
# ============================================================================

@pytest.fixture
def mock_db():
    """Create a MongoDBClient backed by mongomock for unit tests."""
    client = MongoDBClient.__new__(MongoDBClient)
    mock_client = mongomock.MongoClient()
    client.client = mock_client
    client.db = mock_client["hkjc_test"]
    client.matches_current = client.db["matches_current"]
    client.odds_history = client.db["odds_history"]
    client.watch_rules = client.db["watch_rules"]
    client.scheduled_jobs = client.db["scheduled_jobs"]

    # Create unique index on watch_rules.name (mongomock supports this)
    client.watch_rules.create_index("name", unique=True)
    client.scheduled_jobs.create_index("dedup_key", unique=True)

    yield client

    mock_client.close()


# ============================================================================
# MongoDB fixtures (real MongoDB for integration tests)
# ============================================================================

@pytest.fixture
def real_db():
    """Create a MongoDBClient with real MongoDB for integration tests.

    Uses 'hkjc_test' database and cleans up after the test.
    """
    from hkjc_scrapper.config import Settings

    settings = Settings()
    db = MongoDBClient(settings.MONGODB_URI, "hkjc_test")

    # Clean before test
    db.db.drop_collection("matches_current")
    db.db.drop_collection("odds_history")
    db.db.drop_collection("watch_rules")
    db.db.drop_collection("odds_types_ref")
    db.db.drop_collection("tournaments_ref")
    db.db.drop_collection("scheduled_jobs")

    # Re-assign collection refs after drop
    db.matches_current = db.db["matches_current"]
    db.odds_history = db.db["odds_history"]
    db.watch_rules = db.db["watch_rules"]
    db.scheduled_jobs = db.db["scheduled_jobs"]

    yield db

    # Clean after test
    db.db.drop_collection("matches_current")
    db.db.drop_collection("odds_history")
    db.db.drop_collection("watch_rules")
    db.db.drop_collection("odds_types_ref")
    db.db.drop_collection("tournaments_ref")
    db.db.drop_collection("scheduled_jobs")
    db.close()
