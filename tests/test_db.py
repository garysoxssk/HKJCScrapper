"""Unit tests for db.py using mongomock (no real MongoDB required)."""

import pytest
from pymongo.errors import DuplicateKeyError

from hkjc_scrapper.models import (
    MatchFilter,
    Observation,
    Schedule,
    ScheduleTrigger,
    WatchRule,
)


# ============================================================================
# Match operations
# ============================================================================

class TestMatchOperations:
    """Tests for match CRUD operations."""

    def test_upsert_match(self, mock_db, sample_match):
        """Test inserting a new match."""
        mock_db.upsert_match(sample_match)

        doc = mock_db.matches_current.find_one({"_id": sample_match.id})
        assert doc is not None
        assert doc["frontEndId"] == "FB9999"
        assert doc["homeTeam"]["name_en"] == "Manchester United"
        assert doc["awayTeam"]["name_en"] == "Liverpool"
        assert "fetchedAt" in doc

    def test_upsert_match_updates_existing(self, mock_db, sample_match):
        """Test that upserting the same match ID updates the document."""
        mock_db.upsert_match(sample_match)

        # Modify and upsert again
        updated = sample_match.model_copy(update={"status": "FIRSTHALF"})
        mock_db.upsert_match(updated)

        doc = mock_db.matches_current.find_one({"_id": sample_match.id})
        assert doc["status"] == "FIRSTHALF"

        # Should still be only one document
        count = mock_db.matches_current.count_documents({})
        assert count == 1

    def test_get_match_found(self, mock_db, sample_match):
        """Test retrieving an existing match."""
        mock_db.upsert_match(sample_match)

        doc = mock_db.get_match(sample_match.id)
        assert doc is not None
        assert doc["frontEndId"] == "FB9999"

    def test_get_match_not_found(self, mock_db):
        """Test retrieving a non-existent match."""
        doc = mock_db.get_match("nonexistent")
        assert doc is None

    def test_save_matches_batch(self, mock_db, sample_match):
        """Test batch saving matches with odds snapshots."""
        result = mock_db.save_matches([sample_match])

        assert result["matches_upserted"] == 1
        assert result["odds_snapshots"] == 1  # 1 foPool (HAD)

        # Verify match was saved
        match_doc = mock_db.get_match(sample_match.id)
        assert match_doc is not None

        # Verify odds history was created
        history = list(mock_db.odds_history.find({"matchId": sample_match.id}))
        assert len(history) == 1
        assert history[0]["oddsType"] == "HAD"
        assert history[0]["matchDescription"] == "Manchester United vs Liverpool"

    def test_save_matches_empty_list(self, mock_db):
        """Test saving an empty list of matches."""
        result = mock_db.save_matches([])
        assert result["matches_upserted"] == 0
        assert result["odds_snapshots"] == 0


# ============================================================================
# Odds history operations
# ============================================================================

class TestOddsHistory:
    """Tests for odds history operations."""

    def test_insert_odds_snapshot(self, mock_db):
        """Test inserting a single odds snapshot."""
        mock_db.insert_odds_snapshot(
            match_id="M001",
            match_description="Team A vs Team B",
            odds_type="HAD",
            lines=[{"lineId": "L1", "status": "SELLINGSTARTED"}],
            inplay=False,
        )

        docs = list(mock_db.odds_history.find({"matchId": "M001"}))
        assert len(docs) == 1
        assert docs[0]["oddsType"] == "HAD"
        assert docs[0]["inplay"] is False
        assert "fetchedAt" in docs[0]

    def test_get_odds_history_by_match(self, mock_db):
        """Test querying odds history by match ID."""
        # Insert multiple snapshots
        for odds_type in ["HAD", "HHA", "CHL"]:
            mock_db.insert_odds_snapshot(
                match_id="M001",
                match_description="Team A vs Team B",
                odds_type=odds_type,
                lines=[],
            )

        # Also insert for different match
        mock_db.insert_odds_snapshot(
            match_id="M002",
            match_description="Team C vs Team D",
            odds_type="HAD",
            lines=[],
        )

        # Query M001 only
        history = mock_db.get_odds_history("M001")
        assert len(history) == 3

    def test_get_odds_history_by_odds_type(self, mock_db):
        """Test filtering odds history by odds type."""
        for odds_type in ["HAD", "HHA", "HAD"]:
            mock_db.insert_odds_snapshot(
                match_id="M001",
                match_description="Team A vs Team B",
                odds_type=odds_type,
                lines=[],
            )

        history = mock_db.get_odds_history("M001", odds_type="HAD")
        assert len(history) == 2

    def test_get_odds_history_empty(self, mock_db):
        """Test querying odds history with no results."""
        history = mock_db.get_odds_history("nonexistent")
        assert history == []


# ============================================================================
# Watch rule operations
# ============================================================================

class TestWatchRuleOperations:
    """Tests for watch rule CRUD operations."""

    def test_add_watch_rule(self, mock_db, sample_watch_rule):
        """Test adding a new watch rule."""
        mock_db.add_watch_rule(sample_watch_rule)

        doc = mock_db.watch_rules.find_one({"name": sample_watch_rule.name})
        assert doc is not None
        assert doc["name"] == "Test EPL Rule"
        assert doc["enabled"] is True
        assert len(doc["observations"]) == 2
        assert "createdAt" in doc
        assert "updatedAt" in doc

    def test_add_watch_rule_duplicate_name(self, mock_db, sample_watch_rule):
        """Test that duplicate rule names raise an error."""
        mock_db.add_watch_rule(sample_watch_rule)

        with pytest.raises(DuplicateKeyError):
            mock_db.add_watch_rule(sample_watch_rule)

    def test_get_active_watch_rules(self, mock_db):
        """Test retrieving only enabled watch rules."""
        # Add enabled rule
        rule1 = WatchRule(
            name="Active Rule",
            enabled=True,
            match_filter=MatchFilter(tournaments=["EPL"]),
            observations=[
                Observation(
                    odds_types=["HAD"],
                    schedule=Schedule(
                        mode="event",
                        triggers=[ScheduleTrigger(event="at_kickoff")],
                    ),
                )
            ],
        )
        mock_db.add_watch_rule(rule1)

        # Add disabled rule
        rule2 = WatchRule(
            name="Disabled Rule",
            enabled=False,
            match_filter=MatchFilter(tournaments=["LLG"]),
            observations=[
                Observation(
                    odds_types=["CHL"],
                    schedule=Schedule(
                        mode="event",
                        triggers=[ScheduleTrigger(event="at_kickoff")],
                    ),
                )
            ],
        )
        mock_db.add_watch_rule(rule2)

        active = mock_db.get_active_watch_rules()
        assert len(active) == 1
        assert active[0].name == "Active Rule"

    def test_get_all_watch_rules(self, mock_db, sample_watch_rule):
        """Test retrieving all watch rules."""
        mock_db.add_watch_rule(sample_watch_rule)

        # Add another
        rule2 = WatchRule(
            name="Another Rule",
            enabled=False,
            match_filter=MatchFilter(),
            observations=[
                Observation(
                    odds_types=["HAD"],
                    schedule=Schedule(
                        mode="event",
                        triggers=[ScheduleTrigger(event="at_kickoff")],
                    ),
                )
            ],
        )
        mock_db.add_watch_rule(rule2)

        all_rules = mock_db.get_all_watch_rules()
        assert len(all_rules) == 2

    def test_get_watch_rule_by_name(self, mock_db, sample_watch_rule):
        """Test retrieving a single watch rule."""
        mock_db.add_watch_rule(sample_watch_rule)

        doc = mock_db.get_watch_rule("Test EPL Rule")
        assert doc is not None
        assert doc["name"] == "Test EPL Rule"

    def test_get_watch_rule_not_found(self, mock_db):
        """Test retrieving a non-existent watch rule."""
        doc = mock_db.get_watch_rule("nonexistent")
        assert doc is None

    def test_enable_watch_rule(self, mock_db, sample_watch_rule):
        """Test enabling a disabled watch rule."""
        sample_watch_rule.enabled = False
        mock_db.add_watch_rule(sample_watch_rule)

        result = mock_db.enable_watch_rule("Test EPL Rule")
        assert result is True

        doc = mock_db.watch_rules.find_one({"name": "Test EPL Rule"})
        assert doc["enabled"] is True

    def test_disable_watch_rule(self, mock_db, sample_watch_rule):
        """Test disabling an enabled watch rule."""
        mock_db.add_watch_rule(sample_watch_rule)

        result = mock_db.disable_watch_rule("Test EPL Rule")
        assert result is True

        doc = mock_db.watch_rules.find_one({"name": "Test EPL Rule"})
        assert doc["enabled"] is False

    def test_disable_nonexistent_rule(self, mock_db):
        """Test disabling a rule that doesn't exist."""
        result = mock_db.disable_watch_rule("nonexistent")
        assert result is False

    def test_delete_watch_rule(self, mock_db, sample_watch_rule):
        """Test deleting a watch rule."""
        mock_db.add_watch_rule(sample_watch_rule)

        result = mock_db.delete_watch_rule("Test EPL Rule")
        assert result is True

        doc = mock_db.watch_rules.find_one({"name": "Test EPL Rule"})
        assert doc is None

    def test_delete_nonexistent_rule(self, mock_db):
        """Test deleting a rule that doesn't exist."""
        result = mock_db.delete_watch_rule("nonexistent")
        assert result is False

    def test_update_watch_rule(self, mock_db, sample_watch_rule):
        """Test updating a watch rule's fields."""
        mock_db.add_watch_rule(sample_watch_rule)

        result = mock_db.update_watch_rule(
            "Test EPL Rule",
            {"match_filter": {"teams": ["Arsenal"], "tournaments": ["EPL"], "match_ids": []}},
        )
        assert result is True

        doc = mock_db.watch_rules.find_one({"name": "Test EPL Rule"})
        assert doc["match_filter"]["teams"] == ["Arsenal"]


# ============================================================================
# Reference data operations
# ============================================================================

class TestReferenceData:
    """Tests for reference data seeding."""

    def test_seed_reference_data(self, mock_db):
        """Test seeding odds type and tournament reference data."""
        odds_types = [
            {"code": "HAD", "name_en": "Home/Away/Draw", "name_ch": "主客和"},
            {"code": "CHL", "name_en": "Corner Hi-Lo", "name_ch": "角球大細"},
        ]
        tournaments = [
            {"code": "EPL", "name_en": "English Premier League", "name_ch": "英超"},
        ]

        mock_db.seed_reference_data(odds_types, tournaments)

        # Verify
        odds_count = mock_db.db["odds_types_ref"].count_documents({})
        assert odds_count == 2

        tourn_count = mock_db.db["tournaments_ref"].count_documents({})
        assert tourn_count == 1

    def test_seed_reference_data_idempotent(self, mock_db):
        """Test that re-seeding doesn't create duplicates."""
        odds_types = [
            {"code": "HAD", "name_en": "Home/Away/Draw", "name_ch": "主客和"},
        ]
        tournaments = []

        mock_db.seed_reference_data(odds_types, tournaments)
        mock_db.seed_reference_data(odds_types, tournaments)

        odds_count = mock_db.db["odds_types_ref"].count_documents({})
        assert odds_count == 1

    def test_seed_odds_types(self, mock_db):
        """Test seeding odds types only."""
        odds_types = [
            {"code": "HAD", "name_en": "Home/Away/Draw", "name_ch": "主客和"},
            {"code": "CHL", "name_en": "Corner Taken HiLo", "name_ch": "開出角球大細"},
            {"code": "HDC", "name_en": "Handicap", "name_ch": "讓球"},
        ]
        count = mock_db.seed_odds_types(odds_types)
        assert count == 3

        odds_count = mock_db.db["odds_types_ref"].count_documents({})
        assert odds_count == 3


# ============================================================================
# Tournament operations
# ============================================================================

class TestTournamentOperations:
    """Tests for tournament upsert and query operations."""

    def test_upsert_tournaments_insert(self, mock_db):
        """Test inserting new tournaments."""
        tournaments = [
            {
                "id": "50050013",
                "code": "EPL",
                "frontEndId": "FB3397",
                "nameProfileId": "50000051",
                "isInteractiveServiceAvailable": True,
                "name_en": "Eng Premier",
                "name_ch": "英格蘭超級聯賽",
                "sequence": "12.Eng Premier...",
            },
            {
                "id": "50050294",
                "code": "SFL",
                "frontEndId": "FB3742",
                "nameProfileId": "50000100",
                "isInteractiveServiceAvailable": True,
                "name_en": "Spanish Division 1",
                "name_ch": "西班牙甲組聯賽",
                "sequence": "23.Spanish Division 1...",
            },
        ]
        result = mock_db.upsert_tournaments(tournaments)
        assert result["inserted"] == 2
        assert result["updated"] == 0

    def test_upsert_tournaments_no_duplicate(self, mock_db):
        """Test that re-upserting same ID doesn't create duplicates."""
        tournaments = [
            {
                "id": "50050013",
                "code": "EPL",
                "frontEndId": "FB3397",
                "nameProfileId": "50000051",
                "isInteractiveServiceAvailable": True,
                "name_en": "Eng Premier",
                "name_ch": "英格蘭超級聯賽",
                "sequence": "12.Eng Premier...",
            },
        ]
        mock_db.upsert_tournaments(tournaments)
        result = mock_db.upsert_tournaments(tournaments)

        # Second time: 0 inserted (already exists)
        assert result["inserted"] == 0

        total = mock_db.db["tournaments_ref"].count_documents({})
        assert total == 1

    def test_get_tournament_by_id(self, mock_db):
        """Test retrieving a tournament by ID."""
        tournaments = [
            {
                "id": "50050013",
                "code": "EPL",
                "frontEndId": "FB3397",
                "nameProfileId": "",
                "isInteractiveServiceAvailable": True,
                "name_en": "Eng Premier",
                "name_ch": "英格蘭超級聯賽",
                "sequence": "",
            },
        ]
        mock_db.upsert_tournaments(tournaments)

        doc = mock_db.get_tournament_by_id("50050013")
        assert doc is not None
        assert doc["code"] == "EPL"

    def test_get_tournament_by_id_not_found(self, mock_db):
        """Test retrieving a non-existent tournament."""
        doc = mock_db.get_tournament_by_id("nonexistent")
        assert doc is None

    def test_get_tournament_by_code(self, mock_db):
        """Test retrieving tournaments by code."""
        tournaments = [
            {"id": "1", "code": "EPL", "name_en": "Eng Premier", "name_ch": "英超", "sequence": ""},
            {"id": "2", "code": "EPL", "name_en": "Eng Premier 2", "name_ch": "英超2", "sequence": ""},
        ]
        mock_db.upsert_tournaments(tournaments)

        results = mock_db.get_tournament_by_code("EPL")
        assert len(results) == 2

    def test_get_all_tournaments(self, mock_db):
        """Test retrieving all tournaments."""
        tournaments = [
            {"id": "1", "code": "EPL", "name_en": "Eng Premier", "name_ch": "英超", "sequence": ""},
            {"id": "2", "code": "SFL", "name_en": "Spanish Div 1", "name_ch": "西甲", "sequence": ""},
        ]
        mock_db.upsert_tournaments(tournaments)

        all_t = mock_db.get_all_tournaments()
        assert len(all_t) == 2
