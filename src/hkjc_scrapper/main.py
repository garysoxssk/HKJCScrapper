"""HKJC Scrapper - Entry Point.

Usage:
    # Service mode (discovery + scheduled fetches)
    uv run python -m hkjc_scrapper.main

    # Single fetch mode (one cycle, then exit)
    uv run python -m hkjc_scrapper.main --once
"""

import argparse
import logging
import sys

from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.config import Settings
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.scheduler import MatchScheduler


def setup_logging(level: str) -> None:
    """Configure logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Reduce noise from libraries
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="hkjc_scrapper",
        description="HKJC Football Odds Scrapper - Rule-based scheduler",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single fetch cycle then exit (no scheduling loop)",
    )
    args = parser.parse_args(argv)

    # Load settings
    settings = Settings()
    setup_logging(settings.LOG_LEVEL)

    logger = logging.getLogger("hkjc_scrapper")

    # Log startup info
    logger.info("=" * 60)
    logger.info("HKJCScrapper starting...")
    logger.info("  MongoDB: %s / %s", settings.MONGODB_URI, settings.MONGODB_DATABASE)
    logger.info("  API endpoint: %s", settings.GRAPHQL_ENDPOINT)
    logger.info("  Mode: %s", "single fetch" if args.once else "service")
    if not args.once:
        logger.info(
            "  Discovery interval: %ds", settings.DISCOVERY_INTERVAL_SECONDS
        )
    logger.info("=" * 60)

    # Initialize components
    client = HKJCGraphQLClient(settings)
    db = MongoDBClient(settings.MONGODB_URI, settings.MONGODB_DATABASE)
    db.ensure_collections()

    # Log active rule count
    rules = db.get_active_watch_rules()
    logger.info("Active watch rules: %d", len(rules))
    for rule in rules:
        logger.info("  - %s", rule.name)

    scheduler = MatchScheduler(client, db, settings)

    try:
        if args.once:
            # Single fetch mode
            scheduler.run_once()
        else:
            # Service mode
            scheduler.setup_signal_handlers()
            scheduler.start()
            logger.info("Service running. Press Ctrl+C to stop.")
            scheduler.wait()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        if not args.once:
            scheduler.stop()
    finally:
        db.close()
        logger.info("HKJCScrapper stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
