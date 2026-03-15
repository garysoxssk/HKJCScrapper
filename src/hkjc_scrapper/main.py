"""HKJC Scrapper - Entry Point.

Usage:
    # Service mode (discovery + scheduled fetches)
    uv run python -m hkjc_scrapper.main

    # Single fetch mode (one cycle, then exit)
    uv run python -m hkjc_scrapper.main --once
"""

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.config import Settings
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.scheduler import MatchScheduler
from hkjc_scrapper.tg_msg_client import TGMessageClient

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "hkjc_scrapper.log")
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str) -> None:
    """Configure logging to both stdout and rotating file.

    Log files are written to logs/hkjc_scrapper.log with automatic
    rotation at 10 MB, keeping 5 backup files.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (rotating)
    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Reduce noise from libraries
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("telethon").setLevel(logging.WARNING)


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
    # Mask password in URI for logging
    log_uri = settings.MONGODB_URI
    if "@" in log_uri:
        # mongodb+srv://user:password@host -> mongodb+srv://user:***@host
        pre, post = log_uri.split("@", 1)
        if ":" in pre:
            scheme_user = pre.rsplit(":", 1)[0]
            log_uri = f"{scheme_user}:***@{post}"

    logger.info("=" * 60)
    logger.info("HKJCScrapper starting...")
    logger.info("  Profile: %s", settings.APP_ENV)
    logger.info("  MongoDB: %s / %s", log_uri, settings.MONGODB_DATABASE)
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

    # Initialize Telegram client (auto-connects in background thread if enabled)
    tg = TGMessageClient(settings)
    if tg.enabled:
        logger.info("Telegram notifications: enabled")
    else:
        logger.info("Telegram notifications: disabled")

    # Log active rule count
    rules = db.get_active_watch_rules()
    logger.info("Active watch rules: %d", len(rules))
    for rule in rules:
        logger.info("  - %s", rule.name)

    mode = "single fetch" if args.once else "service"
    scheduler = MatchScheduler(client, db, settings, tg=tg)

    # Send startup notification
    if tg.enabled:
        tg.notify_startup(mode, len(rules))

    try:
        if args.once:
            scheduler.run_once()
        else:
            scheduler.setup_signal_handlers()
            scheduler.start()
            logger.info("Service running. Press Ctrl+C to stop.")
            scheduler.wait()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        if not args.once:
            scheduler.stop()
    finally:
        if tg.enabled:
            tg.close()
        db.close()
        logger.info("HKJCScrapper stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
