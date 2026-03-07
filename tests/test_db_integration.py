"""Integration tests for db.py using real MongoDB.

These tests require a running MongoDB instance and are skipped by default.
Run with: pytest -m mongodb
"""

import pytest

from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.reference_data import ODDS_TYPES_DATA, TOURNAMENTS_DATA


@pytest.mark.mongodb
class TestEnsureCollections:
    """Tests for collection and index creation with real MongoDB."""

    def test_ensure_collections_creates_indexes(self, real_db):
        """Test that ensure_collections creates all required indexes."""
        real_db.ensure_collections()

        # Check matches_current indexes
        mc_indexes = real_db.matches_current.index_information()
        assert "status_1" in mc_indexes
        assert "tournament.code_1" in mc_indexes
        assert "matchDate_1" in mc_indexes
        assert "frontEndId_1" in mc_indexes

        # Check watch_rules indexes
        wr_indexes = real_db.watch_rules.index_information()
        assert "name_1" in wr_indexes

    def test_ensure_collections_idempotent(self, real_db):
        """Test that calling ensure_collections twice doesn't error."""
        real_db.ensure_collections()
        real_db.ensure_collections()  # Should not raise

    def test_odds_history_is_timeseries(self, real_db):
        """Test that odds_history is created as a time-series collection."""
        real_db.ensure_collections()

        # Check collection options
        collections_info = list(real_db.db.list_collections(filter={"name": "odds_history"}))
        assert len(collections_info) == 1
        info = collections_info[0]
        assert info["type"] == "timeseries"
        assert info["options"]["timeseries"]["timeField"] == "fetchedAt"
        assert info["options"]["timeseries"]["metaField"] == "matchId"


@pytest.mark.mongodb
class TestMatchOperationsReal:
    """Integration tests for match operations with real MongoDB."""

    def test_save_and_retrieve_match(self, real_db, sample_match):
        """Test full save/retrieve cycle with real MongoDB."""
        real_db.upsert_match(sample_match)

        doc = real_db.get_match(sample_match.id)
        assert doc is not None
        assert doc["homeTeam"]["name_en"] == "Manchester United"
        assert doc["tournament"]["code"] == "EPL"

    def test_save_matches_creates_odds_history(self, real_db, sample_match):
        """Test that save_matches creates both match and odds history records."""
        real_db.ensure_collections()

        result = real_db.save_matches([sample_match])
        assert result["matches_upserted"] == 1
        assert result["odds_snapshots"] == 1

        # Verify odds history
        history = real_db.get_odds_history(sample_match.id)
        assert len(history) == 1
        assert history[0]["oddsType"] == "HAD"

    def test_save_matches_from_sample_file(self, real_db, sample_matches):
        """Test saving real sample API data to MongoDB."""
        real_db.ensure_collections()

        result = real_db.save_matches(sample_matches)
        assert result["matches_upserted"] == len(sample_matches)
        assert result["matches_upserted"] > 0

        # Verify a match can be retrieved
        first = sample_matches[0]
        doc = real_db.get_match(first.id)
        assert doc is not None
        assert doc["frontEndId"] == first.frontEndId


@pytest.mark.mongodb
class TestWatchRulesReal:
    """Integration tests for watch rules with real MongoDB."""

    def test_full_watch_rule_lifecycle(self, real_db, sample_watch_rule):
        """Test add -> list -> disable -> enable -> delete lifecycle."""
        real_db.ensure_collections()

        # Add
        real_db.add_watch_rule(sample_watch_rule)

        # List active
        active = real_db.get_active_watch_rules()
        assert len(active) == 1
        assert active[0].name == "Test EPL Rule"

        # Disable
        real_db.disable_watch_rule("Test EPL Rule")
        active = real_db.get_active_watch_rules()
        assert len(active) == 0

        # Enable
        real_db.enable_watch_rule("Test EPL Rule")
        active = real_db.get_active_watch_rules()
        assert len(active) == 1

        # Delete
        real_db.delete_watch_rule("Test EPL Rule")
        active = real_db.get_active_watch_rules()
        assert len(active) == 0


@pytest.mark.mongodb
class TestReferenceDataReal:
    """Integration tests for reference data with real MongoDB."""

    def test_seed_all_reference_data(self, real_db):
        """Test seeding all odds types and tournaments from reference_data.py."""
        odds_dicts = [ot.model_dump() for ot in ODDS_TYPES_DATA]
        tourn_dicts = [t.model_dump() for t in TOURNAMENTS_DATA]

        real_db.seed_reference_data(odds_dicts, tourn_dicts)

        odds_count = real_db.db["odds_types_ref"].count_documents({})
        assert odds_count == len(ODDS_TYPES_DATA)

        tourn_count = real_db.db["tournaments_ref"].count_documents({})
        assert tourn_count == len(TOURNAMENTS_DATA)

    def test_seed_all_odds_types(self, real_db):
        """Test seeding all 38 odds types from reference_data.py."""
        odds_dicts = [ot.model_dump() for ot in ODDS_TYPES_DATA]
        count = real_db.seed_odds_types(odds_dicts)
        assert count == len(ODDS_TYPES_DATA)

        # Verify a specific one
        doc = real_db.db["odds_types_ref"].find_one({"code": "HAD"})
        assert doc is not None
        assert doc["name_en"] == "Home/Away/Draw"
        assert doc["name_ch"] == "主客和"


@pytest.mark.mongodb
class TestTournamentOperationsReal:
    """Integration tests for tournament operations with real MongoDB."""

    def test_upsert_tournaments_from_sample(self, real_db):
        """Test upserting tournaments from sample API data."""
        import json
        from pathlib import Path

        sample_path = Path(__file__).parent.parent / "resources" / "match-list-res-1.json"
        with open(sample_path) as f:
            data = json.load(f)

        tournaments = data["data"]["tournamentList"]
        result = real_db.upsert_tournaments(tournaments)

        assert result["inserted"] > 0
        assert result["inserted"] == len(tournaments)

        # Verify EPL exists
        epl = real_db.get_tournament_by_code("EPL")
        assert len(epl) > 0
        assert epl[0]["name_en"] == "Eng Premier"

    def test_upsert_tournaments_idempotent(self, real_db):
        """Test that re-upserting same tournaments doesn't create duplicates."""
        tournaments = [
            {
                "id": "50050013",
                "code": "EPL",
                "frontEndId": "FB3397",
                "nameProfileId": "50000051",
                "isInteractiveServiceAvailable": True,
                "name_en": "Eng Premier",
                "name_ch": "英格蘭超級聯賽",
                "sequence": "",
            },
        ]
        real_db.upsert_tournaments(tournaments)
        result = real_db.upsert_tournaments(tournaments)
        assert result["inserted"] == 0

        total = real_db.db["tournaments_ref"].count_documents({})
        assert total == 1
