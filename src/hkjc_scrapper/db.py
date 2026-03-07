"""MongoDB operations for HKJC Scrapper.

Manages three collections:
- matches_current: Latest state of each match (upserted)
- odds_history: Append-only time-series collection for odds tracking
- watch_rules: Configurable observation rules
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import CollectionInvalid

from hkjc_scrapper.models import Match, WatchRule
from hkjc_scrapper.parser import get_match_description

logger = logging.getLogger(__name__)


class MongoDBClient:
    """MongoDB client for HKJC data storage."""

    def __init__(self, uri: str, database: str):
        """
        Initialize MongoDB client.

        Args:
            uri: MongoDB connection string
            database: Database name
        """
        self.client = MongoClient(uri)
        self.db: Database = self.client[database]

        # Collection references
        self.matches_current: Collection = self.db["matches_current"]
        self.odds_history: Collection = self.db["odds_history"]
        self.watch_rules: Collection = self.db["watch_rules"]

    def close(self):
        """Close the MongoDB connection."""
        self.client.close()

    # ========================================================================
    # Collection setup
    # ========================================================================

    def ensure_collections(self):
        """
        Create collections and indexes if they don't exist.

        Creates:
        - matches_current with indexes on status, tournament.code, matchDate
        - odds_history as time-series collection (timeField=fetchedAt, metaField=matchId)
        - watch_rules with unique index on name
        """
        existing = self.db.list_collection_names()

        # Create odds_history as time-series collection if not exists
        if "odds_history" not in existing:
            try:
                self.db.create_collection(
                    "odds_history",
                    timeseries={
                        "timeField": "fetchedAt",
                        "metaField": "matchId",
                        "granularity": "minutes",
                    },
                )
                logger.info("Created odds_history time-series collection")
            except CollectionInvalid:
                logger.info("odds_history collection already exists")

        # Refresh collection references after creation
        self.odds_history = self.db["odds_history"]

        # matches_current indexes
        self.matches_current.create_index("status")
        self.matches_current.create_index("tournament.code")
        self.matches_current.create_index("matchDate")
        self.matches_current.create_index("frontEndId", unique=True, sparse=True)

        # odds_history indexes (compound for efficient queries)
        self.odds_history.create_index([("matchId", 1), ("oddsType", 1), ("fetchedAt", -1)])

        # watch_rules unique index on name
        self.watch_rules.create_index("name", unique=True)

        logger.info("Database collections and indexes ensured")

    # ========================================================================
    # Match operations
    # ========================================================================

    def upsert_match(self, match: Match) -> None:
        """
        Insert or update a match in matches_current.

        Uses match.id as the document _id for upsert.

        Args:
            match: Match object to upsert
        """
        match_dict = match.model_dump()
        match_dict["_id"] = match.id
        match_dict["fetchedAt"] = datetime.now(timezone.utc)

        self.matches_current.replace_one(
            {"_id": match.id},
            match_dict,
            upsert=True,
        )

    def insert_odds_snapshot(
        self,
        match_id: str,
        match_description: str,
        odds_type: str,
        lines: list[dict],
        inplay: bool = False,
    ) -> None:
        """
        Append an odds snapshot to odds_history.

        Args:
            match_id: Match ID
            match_description: Human-readable match description
            odds_type: Odds type code (e.g., "HAD")
            lines: List of line dicts (from FoPool.lines)
            inplay: Whether odds are inplay
        """
        doc = {
            "matchId": match_id,
            "matchDescription": match_description,
            "oddsType": odds_type,
            "inplay": inplay,
            "lines": lines,
            "fetchedAt": datetime.now(timezone.utc),
        }
        self.odds_history.insert_one(doc)

    def save_matches(self, matches: list[Match]) -> dict:
        """
        Batch save matches: upsert matches_current + append odds_history.

        Args:
            matches: List of Match objects

        Returns:
            dict with counts: {"matches_upserted": N, "odds_snapshots": M}
        """
        matches_upserted = 0
        odds_snapshots = 0

        for match in matches:
            # Upsert match state
            self.upsert_match(match)
            matches_upserted += 1

            # Append odds snapshots for each foPool
            match_desc = get_match_description(match)
            for pool in match.foPools:
                lines_data = [line.model_dump() for line in pool.lines]
                self.insert_odds_snapshot(
                    match_id=match.id,
                    match_description=match_desc,
                    odds_type=pool.oddsType,
                    lines=lines_data,
                    inplay=pool.inplay,
                )
                odds_snapshots += 1

        logger.info(
            "Saved %d matches, %d odds snapshots",
            matches_upserted,
            odds_snapshots,
        )
        return {
            "matches_upserted": matches_upserted,
            "odds_snapshots": odds_snapshots,
        }

    def get_match(self, match_id: str) -> Optional[dict]:
        """
        Retrieve a match from matches_current.

        Args:
            match_id: Match ID

        Returns:
            Match document dict or None
        """
        return self.matches_current.find_one({"_id": match_id})

    def get_odds_history(
        self,
        match_id: str,
        odds_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[dict]:
        """
        Query odds history for a match.

        Args:
            match_id: Match ID
            odds_type: Optional odds type filter
            start_time: Optional start of time range
            end_time: Optional end of time range

        Returns:
            List of odds history documents, sorted by fetchedAt ascending
        """
        query: dict = {"matchId": match_id}

        if odds_type:
            query["oddsType"] = odds_type

        if start_time or end_time:
            time_filter: dict = {}
            if start_time:
                time_filter["$gte"] = start_time
            if end_time:
                time_filter["$lte"] = end_time
            query["fetchedAt"] = time_filter

        return list(
            self.odds_history.find(query).sort("fetchedAt", 1)
        )

    # ========================================================================
    # Watch rule operations
    # ========================================================================

    def add_watch_rule(self, rule: WatchRule) -> None:
        """
        Add a new watch rule.

        Args:
            rule: WatchRule object

        Raises:
            pymongo.errors.DuplicateKeyError: If rule name already exists
        """
        doc = rule.model_dump()
        doc["createdAt"] = datetime.now(timezone.utc)
        doc["updatedAt"] = datetime.now(timezone.utc)
        self.watch_rules.insert_one(doc)
        logger.info("Added watch rule: %s", rule.name)

    def get_active_watch_rules(self) -> list[WatchRule]:
        """
        Get all enabled watch rules.

        Returns:
            List of WatchRule objects where enabled=True
        """
        docs = self.watch_rules.find({"enabled": True})
        rules = []
        for doc in docs:
            # Remove MongoDB-specific fields before parsing
            doc.pop("_id", None)
            doc.pop("createdAt", None)
            doc.pop("updatedAt", None)
            rules.append(WatchRule(**doc))
        return rules

    def get_all_watch_rules(self) -> list[dict]:
        """
        Get all watch rules (enabled and disabled) as raw dicts.

        Returns:
            List of rule documents
        """
        return list(self.watch_rules.find())

    def get_watch_rule(self, name: str) -> Optional[dict]:
        """
        Get a single watch rule by name.

        Args:
            name: Rule name

        Returns:
            Rule document dict or None
        """
        return self.watch_rules.find_one({"name": name})

    def update_watch_rule(self, name: str, updates: dict) -> bool:
        """
        Update a watch rule by name.

        Args:
            name: Rule name
            updates: Dict of fields to update

        Returns:
            True if rule was found and updated
        """
        updates["updatedAt"] = datetime.now(timezone.utc)
        result = self.watch_rules.update_one(
            {"name": name},
            {"$set": updates},
        )
        if result.matched_count > 0:
            logger.info("Updated watch rule: %s", name)
            return True
        return False

    def enable_watch_rule(self, name: str) -> bool:
        """
        Enable a watch rule.

        Args:
            name: Rule name

        Returns:
            True if rule was found and enabled
        """
        return self.update_watch_rule(name, {"enabled": True})

    def disable_watch_rule(self, name: str) -> bool:
        """
        Disable a watch rule.

        Args:
            name: Rule name

        Returns:
            True if rule was found and disabled
        """
        return self.update_watch_rule(name, {"enabled": False})

    def delete_watch_rule(self, name: str) -> bool:
        """
        Delete a watch rule by name.

        Args:
            name: Rule name

        Returns:
            True if rule was found and deleted
        """
        result = self.watch_rules.delete_one({"name": name})
        if result.deleted_count > 0:
            logger.info("Deleted watch rule: %s", name)
            return True
        return False

    # ========================================================================
    # Reference data operations
    # ========================================================================

    def seed_reference_data(self, odds_types: list[dict], tournaments: list[dict]) -> None:
        """
        Seed reference data collections (odds_types_ref, tournaments_ref).

        Uses upsert to avoid duplicates on re-run.

        Args:
            odds_types: List of odds type reference dicts
            tournaments: List of tournament reference dicts
        """
        odds_ref = self.db["odds_types_ref"]
        for ot in odds_types:
            odds_ref.replace_one({"code": ot["code"]}, ot, upsert=True)

        tourn_ref = self.db["tournaments_ref"]
        for t in tournaments:
            tourn_ref.replace_one({"code": t["code"]}, t, upsert=True)

        logger.info(
            "Seeded %d odds types, %d tournaments",
            len(odds_types),
            len(tournaments),
        )
