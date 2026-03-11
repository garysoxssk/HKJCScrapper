# HKJCScrapper

A comprehensive Python system for football betting analytics: crawl HKJC odds and live match events, analyze patterns with machine learning, and optionally automate bet placement.

## Overview

HKJCScrapper is designed as a modular system with four independent components that build on each other:

### Module I - HKJC Odds Crawler [IN PROGRESS]
Fetches football match odds from Hong Kong Jockey Club's GraphQL API using a **rule-based scheduler**. Instead of blindly polling everything, you configure watch rules to observe specific matches (by team/tournament), specific odds types, and fetch at configured times (before kickoff, at halftime, continuously during match).

**Status**: Phase 8 complete (scheduler + entry point). Milestone 2 reached -- full rule-based pipeline running end-to-end.

### Module II - 3rd Party Football Events Crawler [NOT STARTED]
Captures live match events (corner kicks, goals, cards, substitutions) with timestamps from an external API. Aligns with HKJC match data using team names + kickoff time for combined analysis.

### Module III - Machine Learning & Data Analytics [NOT STARTED]
Analyzes historical odds and match events to find profitable patterns, builds predictive models, and backtests strategies. Produces actionable signals like "bet CHL High when X condition is met at odds > Y".

### Module IV - Automated Bet Placement [NOT STARTED]
Optionally automates bet placement on HKJC using Playwright + stealth mode. **Note**: This violates HKJC Terms of Service and carries account suspension risk. Modules I-III are designed to work standalone, producing signals a human can act on manually.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  Module I        │     │  Module II       │
│  HKJC Odds       │     │  3rd Party       │
│  Crawler         │     │  Events Crawler  │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         ▼                        ▼
    ┌────────────────────────────────┐
    │     MongoDB (shared)           │
    │  matches_current               │
    │  odds_history (time-series)    │
    │  watch_rules                   │
    │  match_events                  │
    └────────────┬───────────────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │  Module III             │
    │  ML & Analytics         │
    │  (backtesting, signals) │
    └────────────┬────────────┘
                 │
                 ▼
    ┌────────────────────────┐
    │  Module IV              │
    │  Bet Placement          │
    │  (Playwright + stealth) │
    └────────────────────────┘
```

## Tech Stack

- **Language**: Python 3.11+
- **Package Manager**: uv
- **Database**: MongoDB 8.x (with time-series collections)
- **Data Models**: Pydantic v2
- **Scheduling**: APScheduler (rule-based, two-layer scheduler)
- **HTTP Client**: requests with browser simulation
- **Configuration**: pydantic-settings + .env

## Key Features

- **Watch Rules System**: Configure what to observe (teams, tournaments, odds types) and when (before kickoff, halftime, continuous during match)
- **Two-Layer Scheduler**: Discovery job finds matches matching rules, fetch jobs execute at computed times
- **Time-Series Storage**: MongoDB time-series collections for efficient odds history queries (~200K docs/day)
- **Reference Data**: Built-in lookups for 18 odds types (HAD, CHL, HDC, etc.) and 8 tournaments (EPL, LLG, UCL, etc.)
- **Match Alignment**: Cross-module matching via team names + kickoff time for integrating HKJC and 3rd party data

## Quick Start (Docker)

The fastest way to get everything running. Requires [Docker](https://docs.docker.com/get-docker/) and Docker Compose.

```bash
# Clone the repository
git clone <repository-url>
cd HKJCScrapper

# Start MongoDB + scrapper service
docker compose up -d

# Check status
docker compose ps
docker compose logs -f scrapper

# Add a watch rule (via the running container)
docker compose exec scrapper uv run python -m hkjc_scrapper.cli add-rule \
  --name "EPL HAD" --tournaments "EPL" \
  --observation "HAD,HHA:event:before_kickoff:30"

# Run a one-shot fetch
docker compose run --rm scrapper uv run python -m hkjc_scrapper.main --once

# Seed reference data (odds types)
docker compose exec scrapper uv run python -c "
from hkjc_scrapper.config import Settings
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.reference_data import ODDS_TYPES_DATA
db = MongoDBClient(Settings().MONGODB_URI, Settings().MONGODB_DATABASE)
db.seed_odds_types([ot.model_dump() for ot in ODDS_TYPES_DATA])
db.close()
"

# Check data in MongoDB
docker compose exec mongodb mongosh hkjc --quiet --eval "
print('matches:', db.matches_current.countDocuments({}));
print('odds_history:', db.odds_history.countDocuments({}));
print('watch_rules:', db.watch_rules.countDocuments({}));
print('tournaments:', db.tournaments_ref.countDocuments({}));
"

# Stop everything (data persists in Docker volume)
docker compose down

# Stop and delete all data
docker compose down -v
```

### Environment Variables

Override in `docker-compose.yml` under `scrapper.environment`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URI` | `mongodb://mongodb:27017` | MongoDB connection (use `mongodb` hostname inside Docker) |
| `MONGODB_DATABASE` | `hkjc` | Database name |
| `DISCOVERY_INTERVAL_SECONDS` | `900` | Discovery job interval (seconds) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Local Development (without Docker)

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone <repository-url>
cd HKJCScrapper
uv sync

# Copy environment template
cp .env .env
# Edit .env with your MongoDB URI and other settings

# Requires a running MongoDB instance (local or remote)
# Run the bot (service mode)
uv run python -m hkjc_scrapper.main

# Run once (single fetch)
uv run python -m hkjc_scrapper.main --once

# Manage watch rules
uv run python -m hkjc_scrapper.cli list-rules
uv run python -m hkjc_scrapper.cli add-rule --name "EPL HAD" \
  --tournaments "EPL" \
  --observation "HAD,HHA:event:before_kickoff:30"

# Browse live matches and fetch ad-hoc
uv run python -m hkjc_scrapper.cli list-matches --tournament EPL
uv run python -m hkjc_scrapper.cli fetch-match --id 50062141 --odds HAD,HHA

# Query stored data
uv run python -m hkjc_scrapper.cli get-match --tournament EPL
uv run python -m hkjc_scrapper.cli get-odds --id 50062141 --odds HAD --all

# Run tests
uv run pytest
```

## Documentation

- **Command reference**: `docs/commands.md`
- **Database schema**: `docs/database.md`
- **Odds type reference**: `docs/odds_types.md`
- **High-level overview**: `docs/project_modules_high_level.md`
- **Detailed implementation plan**: `docs/project_plan.md`
- **AI agent context**: `CLAUDE.md`
- **HKJC API guide**: `docs/hkjc_api_guide.txt` (Chinese)

## Project Status

| Phase | Component | Status |
|-------|-----------|--------|
| 1 | Project scaffolding | ✅ Complete |
| 2 | Configuration | ✅ Complete |
| 3 | Pydantic models + reference data | ✅ Complete |
| 4 | HKJC API client | ✅ Complete |
| 5 | Response parser | ✅ Complete |
| 6 | MongoDB storage | ✅ Complete |
| 6a | Watch rules CLI | ✅ Complete |
| 7 | Rule-based scheduler | ✅ Complete |
| 8 | Entry point | ✅ Complete |
| 9 | Testing (extended) | ⏳ Pending |
| 10 | Docker deployment | ✅ Complete |

### Test Summary

| Test Suite | Count | Command |
|------------|-------|---------|
| Unit tests (default) | 137 | `uv run pytest` |
| MongoDB integration | 11 | `uv run pytest -m mongodb` |
| Live API integration | 5 | `uv run pytest -m integration` |
| **Total** | **153** | `uv run pytest -m "integration or mongodb" --override-ini="addopts="` |

## Data Collections

- **`matches_current`**: Latest state of each match (upserted)
- **`odds_history`**: Time-series collection for odds movement tracking
- **`watch_rules`**: Configurable observation rules
- **`odds_types_ref`**: Reference data for odds type codes (HAD, CHL, etc.)
- **`tournaments_ref`**: Reference data for tournament codes (EPL, LLG, etc.)

## Legal Notice

**Module IV (automated betting) violates HKJC Terms of Service.** HKJC actively detects and permanently suspends accounts using automation. This module is isolated and optional — the system produces value without it through signals and analytics that can be consumed by a human.

## License

[To be determined]

---

## Summary

**Four-module system for football betting analytics:**

- **Module I** (Milestone 2 reached): Rule-based HKJC odds crawler with configurable watch rules
  - 38 odds types (HAD, Handicaps, Corners, Goal Scorers, Extra Time, etc.)
  - Smart scheduling: before kickoff, at halftime, or continuous during match
  - Two-layer scheduler minimizes API calls while ensuring comprehensive coverage

- **Module II** (Planned): Integrates live match events (corners, goals) from 3rd party APIs
  - Aligns with HKJC data via team names + kickoff time

- **Module III** (Planned): Machine learning for pattern recognition and backtesting
  - Produces actionable betting signals

- **Module IV** (Optional): Playwright-based bet automation
  - **Warning**: Violates HKJC ToS, carries account suspension risk

**Tech**: Python 3.11+, uv, MongoDB 8.x (time-series collections), Pydantic v2, APScheduler

**Design**: MongoDB stores ~200K odds snapshots/day. Modules I-III deliver standalone value without requiring automation.
