# CLAUDE.md - Project Context for AI Agents

## Project Overview

**HKJCScrapper** is a Python bot that automatically fetches football match odds data from the Hong Kong Jockey Club (HKJC) GraphQL API, transforms it into structured Pydantic models, and stores it in MongoDB.

The bot runs as a **rule-based scheduled service**: instead of blindly polling all data, it uses configurable **watch rules** to determine which matches to observe (by team, tournament), which odds types to capture, and when to fetch (before kickoff, at halftime, continuously during match, etc.).

## Long-Term Vision (4 Modules)

This project is **Module I** of a larger system. See `docs/project_tracker.md` for the full roadmap:

| Module | Purpose | Status |
| ------ | ------- | ------ |
| **I - HKJC Odds Crawler** | Fetch & store odds data from HKJC GraphQL API | **In Progress** (Phase 1 complete) |
| II - 3rd Party Events | Crawl live match events (corner kicks, goals, etc.) from a 3rd party API | Not started (API TBD) |
| III - ML & Analytics | Backtesting, strategy analysis, odds-vs-events correlation | Not started |
| IV - Bet Placement | Playwright-based automated betting (optional, carries ToS risks) | Not started |

### Cross-Module Design Considerations (decided)
- **MongoDB is the single database** for all modules. No need for a separate time-series DB — MongoDB 5.0+ native time-series collections handle the volume (polling ~60 matches every 5 min).
- **`odds_history` should use MongoDB time-series collection** format (with `timeField`, `metaField`) for efficient time-range queries needed by Module III backtesting.
- **Match schema must include enough metadata** (team names, kickoff time, tournament) for fuzzy-matching against 3rd party data in Module II — since HKJC match IDs won't exist in external APIs.
- **Module II match alignment**: Match IDs between HKJC and 3rd party APIs will be aligned by `team name + match date + kickoff time`. Timezone normalization is critical to avoid mismatches.
- **Module IV (bet automation) violates HKJC Terms of Service** and risks account suspension. Design Modules I-III to produce signals/recommendations that work standalone; treat automation as an isolated, optional extension.
- **Module IV will use Playwright + stealth** (not Selenium). Playwright is faster, has better anti-detection via `playwright-stealth`, and native async support. Decision: fully automated (no human-in-the-loop).
- **Data retention**: Plan for TTL indexes or archival (e.g., Parquet export) since odds_history grows ~200K documents/day during heavy match periods.

## Tech Stack & Decisions

| Component        | Choice             | Reason                                           |
| ---------------- | ------------------ | ------------------------------------------------ |
| Language         | Python 3.11+       | User preference                                  |
| Package Manager  | uv                 | Fast, modern Python package manager              |
| HTTP Client      | requests (Session) | Simulates browser with required headers           |
| Database         | MongoDB (pymongo)  | Stores nested JSON natively, configurable host, time-series collection support |
| Data Models      | Pydantic v2        | Validation + serialization of API responses       |
| Configuration    | pydantic-settings  | Loads from `.env` file with type-safe defaults    |
| Scheduling       | APScheduler        | Rule-based scheduling with date and interval triggers |
| Build System     | hatchling          | Specified in pyproject.toml                      |

## Project Structure

```
HKJCScrapper/
├── src/hkjc_scrapper/       # Main package (src layout)
│   ├── __init__.py
│   ├── config.py            # Settings via pydantic-settings + .env
│   ├── client.py            # HKJC GraphQL API client (requests.Session)
│   ├── models.py            # Pydantic data models (API response + WatchRule)
│   ├── parser.py            # Raw JSON -> Pydantic model transformation
│   ├── db.py                # MongoDB connection & CRUD (matches, odds, rules)
│   ├── cli.py               # CLI for managing watch rules
│   ├── scheduler.py         # Rule-based scheduler (discovery + fetch jobs)
│   └── main.py              # CLI entry point (--once or service mode)
├── tests/                   # pytest test suite
├── docs/
│   ├── project_tracker.md   # High-level 4-module roadmap
│   ├── project_plan.md      # Detailed Module I plan with verification steps
│   ├── hkjc_api_guide.txt   # Full API guide (Chinese) explaining GraphQL endpoints
│   └── api/
│       └── base_api_sample_response.json  # Real sample response (~125KB)
├── .env.example             # Template for environment variables
├── .gitignore
├── pyproject.toml           # uv/hatchling project config
└── CLAUDE.md                # This file
```

## Key Architecture Decisions

1. **MongoDB with three collections**:
   - `matches_current`: Upserted on each fetch (keyed by match ID). Latest state only.
   - `odds_history`: Append-only time-series collection. One document per (match, oddsType) per fetch cycle. Enables odds movement analysis.
   - `watch_rules`: Configurable rules defining which matches/odds to observe and when.

2. **Watch rules system** (replaces global ODDS_TYPES/POLL_INTERVAL):
   - Rules stored in MongoDB `watch_rules` collection, managed via CLI scripts.
   - Each rule has: match filter (teams, tournaments), odds types, and schedule (event-based or continuous).
   - Schedule triggers: `before_kickoff`, `at_kickoff`, `at_halftime`, `after_kickoff`, `continuous` (with interval).
   - Example: "Observe HAD for all Man Utd EPL games 30min before kickoff" or "Poll CHL every 5min during all La Liga matches".

3. **Two-layer scheduler**:
   - **Discovery job** (every ~15min): Fetches basic match list, matches against watch rules, schedules fetch jobs.
   - **Fetch jobs**: One-shot (APScheduler `date` trigger) or repeating (APScheduler `interval` trigger) based on rule schedule.

4. **Browser simulation**: The HKJC API requires specific headers (User-Agent, Referer: `https://bet.hkjc.com/`, CORS sec-fetch-* headers) and an OPTIONS preflight before POST. The client must replicate this sequence.

5. **src layout**: Package code lives in `src/hkjc_scrapper/` (not top-level). This is configured in `pyproject.toml` under `[tool.hatch.build.targets.wheel]`.

## HKJC API Summary

- **Endpoint**: `https://info.cld.hkjc.com/graphql/base/` (POST)
- **Authentication**: None, but requires browser-like headers
- **Query Whitelisting**: API only accepts specific pre-approved query formats. Custom queries return `"query isn't whitelisted"` error. Must use exact query structure from `resources/single-match-req-1.txt` with all parameters defined.
- **Request flow**: OPTIONS preflight -> POST match list query (with odds types filter)
- **Response structure**: `{ "data": { "matches": [ ... ] } }`
- **Field naming**: Mix of snake_case (name_en, name_ch) and camelCase (frontEndId, kickOffTime)
- **Each match contains**: id, frontEndId, matchDate, kickOffTime, status, homeTeam, awayTeam, tournament, poolInfo, runningResult, foPools (odds data), liveEvents, venue, tvChannels, and more
- **foPools structure**: Each pool has an `oddsType` (e.g. "HHA"), `lines` (each with a `condition` like "-2.0"), and `combinations` (each with `currentOdds` and `selections`)
- **Full API guide**: `docs/hkjc_api_guide.txt` (Chinese, comprehensive)
- **Sample responses**: `docs/api/base_api_sample_response.json` and `resources/single-match-res-1.json` (real API capture)

### Odds Type Codes
HAD (Home/Away/Draw), EHA (Early HAD), HHA (Handicap), HDC (Asian Handicap), HIL (Hi-Lo), CHL (Corner Hi-Lo), CRS (Correct Score), TTG (Total Goals), NTS (Next Team to Score), CHD (Corner HAD), FHA (First Half HAD), FHL (First Half Hi-Lo), FHH (First Half Handicap), FCS (First Correct Score), OOE (Odd/Even), FTS (First Team to Score), FGS (First Goal Scorer), AGS (Anytime Goal Scorer)

### Match Status Values
SCHEDULED, FIRSTHALF, SECONDHALF, HALFTIME, FULLTIME

### Pool/Line/Combination Statuses
- Pool: SELLINGSTARTED, SUSPENDED, PAYOUTSTARTED
- Combination: AVAILABLE, WIN, LOSE

## Development Commands

```bash
# Install dependencies
uv sync

# Run the bot (service mode)
uv run python -m hkjc_scrapper.main

# Run once (single fetch)
uv run python -m hkjc_scrapper.main --once

# Run tests
uv run pytest tests/ -v

# Add a new dependency
uv add <package-name>

# Manage watch rules
uv run python -m hkjc_scrapper.cli list-rules
uv run python -m hkjc_scrapper.cli add-rule --name "..." --tournaments "EPL" --observation "HAD:event:before_kickoff:30"
uv run python -m hkjc_scrapper.cli disable-rule --name "..."
```

## Environment Variables

See `.env.example` for all available config. Key ones:
- `MONGODB_URI` - MongoDB connection string (default: `mongodb://localhost:27017`)
- `MONGODB_DATABASE` - Database name (default: `hkjc`)
- `GRAPHQL_ENDPOINT` - API URL (default: `https://info.cld.hkjc.com/graphql/base/`)
- `DISCOVERY_INTERVAL_SECONDS` - How often to discover matches and evaluate rules (default: `900`)
- `START_INDEX` / `END_INDEX` - Pagination range (default: 1/60)
- `LOG_LEVEL` - Logging level (default: `INFO`)

Note: `POLL_INTERVAL_SECONDS` and `ODDS_TYPES` are no longer global — they are configured per watch rule.

## Current Progress

**Phase 1 (Project Scaffolding) - COMPLETE**
- uv (v0.10.4) installed and project initialized
- pyproject.toml configured with hatchling build system
- src layout created with all 8 module files (placeholder content)
- All dependencies installed and importable (requests, pymongo, pydantic, pydantic-settings, apscheduler)
- .env.example and .gitignore created
- Verified: `uv run python -c "import requests; import pymongo; ..."` passes

**Phase 2 (Configuration) - COMPLETE**
- Implemented `Settings` class with pydantic-settings
- Loads from .env or defaults (MONGODB_URI, GRAPHQL_ENDPOINT, DISCOVERY_INTERVAL_SECONDS, etc.)
- Verified: environment variable override works

**Phase 3 (Pydantic Models) - COMPLETE**
- Created all API response models (Team, Tournament, Match, FoPool, Line, Combination, etc.)
- Created watch rule models (WatchRule, MatchFilter, Observation, Schedule)
- Added enums (OddsType, TournamentCode, MatchStatus, PoolStatus, CombinationStatus)
- Created reference data models (OddsTypeReference, TournamentReference)
- Added reference_data.py with seed data for 18 odds types and 8 tournaments
- Verified: Sample response parses successfully through models

**Phase 4 (API Client) - COMPLETE**
- Implemented `HKJCGraphQLClient` with GraphQL query templates
- Browser simulation headers (User-Agent, Referer, CORS headers)
- Methods: send_options_preflight(), send_basic_match_list_request(), send_detailed_match_list_request(), fetch_matches_for_odds()
- Error handling with timeouts and retries
- Rate limiting with configurable delays
- **CRITICAL FIX**: HKJC API uses query whitelisting - GraphQL query structure must exactly match approved format from real API. Updated to use whitelisted `matchList` query with all parameters defined (even if unused/null). See `resources/single-match-req-1.txt` for reference query.

**Phase 5 (Response Parser) - COMPLETE**
- Implemented parse_matches_response() - validates and parses API JSON into Match models
- Implemented filter_matches_by_rule() - filters by team/tournament/match ID
- Implemented filter_fopools_by_odds_types() - filters odds pools by type
- Verified: Sample response parses successfully, filters work correctly

**Phase 6 (MongoDB Storage) - COMPLETE**
- Implemented `MongoDBClient` in `src/hkjc_scrapper/db.py`
- Three collections: `matches_current` (upserted), `odds_history` (time-series), `watch_rules` (CRUD)
- `odds_history` created as MongoDB time-series collection (timeField=fetchedAt, metaField=matchId)
- Indexes: status, tournament.code, matchDate on matches; compound (matchId, oddsType, fetchedAt) on odds_history; unique name on watch_rules
- Methods: upsert_match, insert_odds_snapshot, save_matches, get_match, get_odds_history
- Watch rules CRUD: add, get_active, get_all, get_by_name, update, enable, disable, delete
- Reference data seeding: seed_reference_data()

**Phase 6a (Watch Rules CLI) - COMPLETE**
- Implemented CLI in `src/hkjc_scrapper/cli.py` using argparse
- Commands: add-rule, list-rules, show-rule, enable-rule, disable-rule, delete-rule
- Observation string parser: `"HAD,HHA:event:before_kickoff:30"` or `"CHL:continuous:300:kickoff:fulltime"`
- Table output for list-rules, detailed output for show-rule

**Testing Infrastructure - COMPLETE**
- Added pytest, pytest-mock, and mongomock as dev dependencies
- Created pytest.ini with three markers: default (unit), `integration` (live API), `mongodb` (real MongoDB)
- Unit tests use mongomock (no external dependencies needed)
- MongoDB integration tests use `hkjc_test` database with auto-cleanup
- **Test counts**: 70 unit tests + 8 mongodb integration + 4 API integration = 82 total
- All tests passing

**Phase 7 (Rule-Based Scheduler) - NOT STARTED** <-- Start here
- See `docs/project_plan.md` for full details and verification steps

**Phases 8-10** - See `docs/project_plan.md` for full details and verification steps for each phase.

## Coding Conventions

- **Models**: Use Pydantic v2 `BaseModel` with `model_config = ConfigDict(...)` (not v1 `class Config`)
- **Config**: Use `pydantic-settings` `BaseSettings` with `.env` file loading
- **Imports**: Use the package name `hkjc_scrapper` (e.g. `from hkjc_scrapper.config import Settings`)
- **Entry point**: `uv run python -m hkjc_scrapper.main` (the `__main__` pattern)
- **No over-engineering**: Keep it simple. Only implement what's needed for the current phase.
- **Error handling**: Log and continue on transient API failures; don't crash the polling loop.
- **Fields**: Use snake_case for Python attributes. The HKJC API also uses snake_case (name_en, name_ch), so no aliases needed for most fields. Some fields use camelCase (frontEndId, kickOffTime) - these are used as-is in both API and models.

## Session Notes

- **CLAUDE.md auto-update**: User requested that CLAUDE.md is updated at the end of every conversation to preserve context for future AI agent sessions.
- **MongoDB confirmed over time-series DB**: Discussed whether to use TimescaleDB/InfluxDB. Decided MongoDB is sufficient — use native time-series collections (MongoDB 5.0+) for `odds_history`. Data volume (~200K docs/day peak) is well within MongoDB's capability. InfluxDB rejected because HKJC data is deeply nested (Match → foPools → lines → combinations → selections) — flattening for InfluxDB would lose structure and add complexity.
- **3rd party API for Module II**: Not yet decided. Schema should include enough match metadata (team names, kickoff time, tournament code) to enable fuzzy matching with external data sources later.
- **Match ID alignment across modules**: Will use `team name + match date + kickoff time` for cross-module matching. Timezone normalization is critical — all timestamps should be stored/compared in a consistent timezone (UTC or HK time +08:00).
- **Module IV legal note**: HKJC ToS prohibits bot interaction. Module IV should be isolated and optional. Modules I-III designed to work standalone, producing signals a human could act on.
- **Module IV tech**: Playwright + `playwright-stealth` chosen over Selenium. Faster, better anti-detection, native async. Fully automated (no human confirmation step).
- **Watch rules system**: Major design decision — replaced simple fixed-interval polling with a rule-based system. Rules stored in MongoDB `watch_rules` collection, managed via CLI. Each rule specifies match filters (teams/tournaments), odds types, and fetch schedule (event-based triggers or continuous polling). This enables selective observation like "HAD for Man Utd EPL games before kickoff" or "CHL for all La Liga games every 5min during match".
- **Scheduler redesign**: Two-layer architecture. Layer 1 (Discovery) runs periodically to find matches matching rules. Layer 2 (Fetch jobs) are scheduled at computed times using APScheduler date/interval triggers.
- **MongoDB 8.2 installed locally**: Development uses local MongoDB 8.2. Design must support migration to cloud-hosted MongoDB (e.g. Atlas) later — connection string is already configurable via `MONGODB_URI` env var. Data migration will be needed when moving to cloud.
- **Docs structure**: `docs/project_modules_high_level.md` = high-level 4-module roadmap. `docs/project_plan.md` = detailed Module I implementation phases with verification steps.
- **Reference data system**: User requested enums/lookups for odds types and tournaments. Implemented as: (1) Python Enums in models.py for validation, (2) Pydantic reference models (OddsTypeReference, TournamentReference), (3) Seed data in reference_data.py with 18 odds types and 8 tournaments. Will be stored in MongoDB `odds_types_ref` and `tournaments_ref` collections for querying from dashboards/analytics.
- **HKJC API Query Whitelisting Discovery**: Integration tests initially failed with "query isn't whitelisted" error. Discovered HKJC API doesn't accept arbitrary GraphQL queries - only specific pre-approved query structures. Solution: Use exact query format from real API request (see `resources/single-match-req-1.txt`), including ALL parameters defined in query signature even if passed as null/unused. The whitelisted query has ~13 parameters (startIndex, endIndex, startDate, endDate, matchIds, tournIds, fbOddsTypes, fbOddsTypesM, inplayOnly, featuredMatchesOnly, frontEndIds, earlySettlementOnly, showAllMatch). All client methods now use this single whitelisted query format.
- **API Field Naming**: Initially assumed HKJC API used camelCase (nameEn, nameCh). Real API uses snake_case (name_en, name_ch) for most fields. Some fields like frontEndId, kickOffTime use camelCase. Models updated accordingly. Added new models: Venue, LiveEvent, NgsInfo, AgsInfo, Remark, AdminOperation to handle all fields in real API response.
- **Real API Samples**: User provided actual API request/response samples in `resources/` directory (`single-match-req-1.txt`, `single-match-res-1.json`). These are the authoritative reference for query structure and response format. Integration tests now successfully fetch live data from HKJC API (tested with 81 matches).
- **MongoDB Testing Strategy**: User chose "both approaches" for testing: (1) mongomock for unit tests (fast, no external dependency), (2) real MongoDB with `hkjc_test` database for integration tests (supports time-series collections, real indexes). Tests marked with `@pytest.mark.mongodb` for the real DB tests.
- **Phase 6 MongoDB Implementation**: Implemented MongoDBClient with three collections. `odds_history` uses MongoDB time-series collection (timeField=fetchedAt, metaField=matchId, granularity=minutes). All timestamps stored as UTC. `save_matches()` does both match upsert and odds history append in one call. Reference data seeding uses upsert to be idempotent.
- **Phase 6a CLI Implementation**: Watch rules CLI uses argparse with subcommands. Observation string format: `"ODDS:MODE:DETAILS"` where MODE is `event` or `continuous`. Example: `"HAD,HHA:event:before_kickoff:30"` means "fetch HAD and HHA odds 30 minutes before kickoff". CLI connects to MongoDB on each invocation (stateless).
