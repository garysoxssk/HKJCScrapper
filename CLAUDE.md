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

## Environment Profiles

Two profiles via `APP_ENV` env var:
- `APP_ENV=local` (default) - loads `.env.local`, local MongoDB
- `APP_ENV=prod` - loads `.env.prod`, MongoDB Atlas (password via `MONGODB_PASSWORD` env var)

See `.env.example` for all available config. Key ones:
- `MONGODB_URI` - MongoDB connection string (local profile)
- `MONGODB_USER` / `MONGODB_PASSWORD` / `MONGODB_HOST` - Atlas connection (prod profile, URI built from parts)
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
- **Test counts**: 137 unit tests + 11 mongodb integration + 5 API integration = 153 total
- All tests passing

**Reference Data Enhancements - COMPLETE**
- 38 odds types sourced from HKJC API description files (LB_FB_TITLE_ labels) with EN/CH translations
- Tournament list fetched via GraphQL `tournamentList` query and stored in `tournaments_ref` collection
- `send_tournament_list_request()` in client.py for fetching all tournaments
- `upsert_tournaments()` in db.py - insert-if-new, update-if-exists (keyed by tournament ID)
- `seed_odds_types()` in db.py for one-time odds type seeding
- Documentation: `docs/odds_types.md` with full table of all supported odds types

**Phase 7 (Rule-Based Scheduler) - COMPLETE**
- `MatchScheduler` class in `src/hkjc_scrapper/scheduler.py`
- Two-layer architecture: Discovery (periodic) + Fetch (scheduled at computed times)
- Event mode: APScheduler `date` trigger for one-shot fetches (before_kickoff, at_kickoff, at_halftime, after_kickoff)
- Continuous mode: APScheduler `interval` trigger between start/end events (e.g., kickoff to fulltime)
- Deduplication: tracks scheduled keys to avoid duplicate jobs
- Graceful shutdown via SIGINT/SIGTERM signal handlers
- Tournament discovery integrated into each discovery cycle
- Helper functions: `parse_kickoff_time()`, `compute_trigger_time()`, `compute_event_boundary()`
- 20 unit tests for time computation and scheduling logic

**Phase 8 (Entry Point) - COMPLETE**
- `src/hkjc_scrapper/main.py` with argparse CLI
- `--once` flag for single fetch cycle (useful for testing)
- Default mode: starts discovery + scheduler loop
- Structured logging with configurable level (LOG_LEVEL)
- Startup info logging: MongoDB URI, endpoint, mode, active rule count
- `__main__.py` for `python -m hkjc_scrapper` support

**Phase 10 (Docker Deployment) - COMPLETE**
- `Dockerfile` using `python:3.13-slim` + uv from `ghcr.io/astral-sh/uv:latest`
- `docker-compose.yml` with MongoDB 8 + scrapper service
- MongoDB health check, volume persistence, proper service dependency
- Tested: both containers start, scrapper connects to MongoDB, discovery runs, 134 tournaments fetched
- `.dockerignore` excludes tests, docs, IDE files from production image

**Telegram Notifications - COMPLETE**
- `TGMessageClient` in `src/hkjc_scrapper/tg_msg_client.py` using Telethon (MTProto)
- `TELEGRAM_ENABLED` toggle in config to disable notifications without removing credentials
- Integrated into scheduler: discovery (when jobs scheduled), fetch (when odds saved)
- Integrated into CLI: `add-rule`, `enable-rule`, `disable-rule`, `delete-rule`, `fetch-match`
- New CLI command: `send-message -m "..."` for one-off custom messages
- Sync wrapper for calling async Telethon from sync scheduler/CLI code
- All sends are fire-and-forget: failures logged but never crash the caller
- 16 unit tests for TG client (mocked, no Telegram connection needed)

**5 Enhancements - COMPLETE**

*Enhancement 5 (Error notifications via TG)*:
- `notify_error(context, error)` in `TGMessageClient` — formats error with HTML, truncates at 200 chars
- Called in scheduler: `execute_fetch()` and `run_discovery()` catch blocks
- 4 tests in test_tg_msg_client.py + 4 tests in test_scheduler.py

*Enhancement 2 (Odds details in fetch TG message)*:
- `TG_FETCH_INCLUDE_ODDS: bool = False` config toggle
- `notify_fetch()` accepts `odds_details: list[dict] | None` — shows ALL lines per pool
- `_format_pool_odds()` helper for HTML-formatted pool odds
- `_extract_odds_details()` helper in scheduler.py extracts from foPools model
- Same pattern in cli.py `cmd_fetch_match()`
- Truncated at 3500 chars if message too long

*Enhancement 3 (Rule details in discovery TG message)*:
- `TG_DISCOVERY_INCLUDE_RULES: bool = False` config toggle
- `notify_discovery()` accepts `rule_details: list[dict] | None` — shows per-rule breakdown
- Scheduler accumulates per-rule stats during discovery loop

*Enhancement 1 (CLI time-series odds reader)*:
- `--time-series` / `--ts` flag on `get-odds` (mutually exclusive with `--all`, `--latest`, etc.)
- `--limit N` optional flag (default None = show all)
- `_print_odds_time_series()` function: detects columns dynamically, shows `^`/`v` change indicators, `*` for line condition changes, range and movement summary
- 6 tests in test_cli.py

*Enhancement 4 (TG bot command listener with inline buttons)*:
- `TG_COMMANDS_ENABLED: bool = False` and `TG_COMMAND_ALLOWED_USERS: str = ""` config fields
- **Two-phase `TGMessageClient` init**: `__init__` stores config only, `start()` starts background thread, `enable_commands(db, api_client)` wires command handler (call before `start()`)
- Background loop switched from sleep-poll to `run_until_disconnected()` for event reception
- `close()` calls `client.disconnect()` to break `run_until_disconnected()`
- New `src/hkjc_scrapper/tg_commands.py`: `TGCommandHandler` with all commands + callbacks + `AddRuleWizard`
- Commands: `/help`, `/status`, `/matches`, `/fetch`, `/odds`, `/rules`, `/addrule`, `/enablerule`, `/disablerule`, `/deleterule`
- All commands guarded by `_check_auth()` (allows all if `TG_COMMAND_ALLOWED_USERS` is empty)
- `/addrule` multi-step wizard with inline buttons for tournament/odds/schedule selection, text prompt for name, 5-min timeout
- `/rules` shows enable/disable/delete buttons per rule; delete requires confirmation
- Sync DB/API calls wrapped in `loop.run_in_executor()` to avoid blocking Telethon
- New `tests/test_tg_commands.py`: 30 unit tests covering auth, help, rules, callbacks, wizard flow, timeout
- `main.py` updated: `tg.enable_commands(db, client)` before `tg.start()`
- `cli.py` updated: `tg.start()` called in `_init_tg()`
- **Total unit tests: 206** (was 162)

**Persistent Job Scheduling - COMPLETE**
- `scheduled_jobs` MongoDB collection with dedup_key (unique), trigger_time, end_time indexes
- 4 CRUD methods in db.py: insert_scheduled_job, delete_scheduled_job, get_all_scheduled_jobs, delete_expired_scheduled_jobs
- Scheduler persists jobs to DB on schedule, cleans up on execution, reloads on startup
- 20 tests in test_scheduled_jobs.py (9 DB layer + 11 scheduler persistence)

**TG Bot Command UX Enhancements - COMPLETE**
- `/rules` now shows full rule details (teams, tournaments, odds types, schedule info) with 1-based index numbers
- `/rules` buttons labeled with index (e.g., "Disable #1", "Delete #2") for clarity with many rules
- `/odds` shows exact fetch timestamp and relative time to kickoff (e.g., "30 min before kickoff", "15 min after kickoff")
- Helper functions: `_format_rule_detail()`, `_format_relative_to_kickoff()` in tg_commands.py
- 12 new tests (6 helper function tests + 3 odds fetch time tests + 2 rules detail/index tests + 1 existing test update)
- `/fetch` response now includes actual odds values (lines, conditions, combinations) from the fetched match's foPools

**Timezone & Scheduler Bugfixes - COMPLETE**
- **Critical bug fix**: `_reload_scheduled_jobs()` used `start_date=now` for continuous jobs, causing them to start immediately after restart regardless of original kickoff boundary. Fixed to use `max(start_time, now)`.
- **Configurable timezone**: `APP_TIMEZONE` setting (default: `Asia/Hong_Kong`) with `settings.tz` cached property returning `ZoneInfo`.
- **HKT log timestamps**: Custom `TZFormatter` in `main.py` converts log timestamps to configured timezone. Startup log shows timezone.
- **Timezone-aware reload**: Added `tzinfo` guards for naive datetimes from MongoDB on event and continuous job reload.
- **Scheduler log readability**: Event/continuous log messages show times with HKT suffix via `.astimezone(HK_TZ)`.

**Scheduled Jobs Viewer - COMPLETE**
- New CLI command: `list-jobs` — shows persisted scheduled jobs with front-end ID, type, odds, trigger/window (in HKT), created time.
- New TG command: `/jobs` — shows scheduled jobs in Telegram with same details.
- Registered in both CLI dispatch and TG `register_handlers()`.
- **Total unit tests: 253** (was 241, +16 deselected integration/mongodb)

**Phase 9 (Extended Testing)** - See `docs/project_plan.md` for details.

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
- **Reference data system**: Implemented as: (1) Python Enums in models.py for validation, (2) Pydantic reference models (OddsTypeReference, TournamentReference), (3) Seed data in reference_data.py with 38 odds types (from HKJC LB_FB_TITLE_ labels) and 8 tournaments. Stored in MongoDB `odds_types_ref` and `tournaments_ref` collections. Tournament data also auto-fetched from HKJC `tournamentList` GraphQL query and upserted by tournament ID.
- **HKJC API Query Whitelisting Discovery**: Integration tests initially failed with "query isn't whitelisted" error. Discovered HKJC API doesn't accept arbitrary GraphQL queries - only specific pre-approved query structures. Solution: Use exact query format from real API request (see `resources/single-match-req-1.txt`), including ALL parameters defined in query signature even if passed as null/unused. The whitelisted query has ~13 parameters (startIndex, endIndex, startDate, endDate, matchIds, tournIds, fbOddsTypes, fbOddsTypesM, inplayOnly, featuredMatchesOnly, frontEndIds, earlySettlementOnly, showAllMatch). All client methods now use this single whitelisted query format.
- **API Field Naming**: Initially assumed HKJC API used camelCase (nameEn, nameCh). Real API uses snake_case (name_en, name_ch) for most fields. Some fields like frontEndId, kickOffTime use camelCase. Models updated accordingly. Added new models: Venue, LiveEvent, NgsInfo, AgsInfo, Remark, AdminOperation to handle all fields in real API response.
- **Real API Samples**: User provided actual API request/response samples in `resources/` directory (`single-match-req-1.txt`, `single-match-res-1.json`). These are the authoritative reference for query structure and response format. Integration tests now successfully fetch live data from HKJC API (tested with 81 matches).
- **MongoDB Testing Strategy**: User chose "both approaches" for testing: (1) mongomock for unit tests (fast, no external dependency), (2) real MongoDB with `hkjc_test` database for integration tests (supports time-series collections, real indexes). Tests marked with `@pytest.mark.mongodb` for the real DB tests.
- **Phase 6 MongoDB Implementation**: Implemented MongoDBClient with three collections. `odds_history` uses MongoDB time-series collection (timeField=fetchedAt, metaField=matchId, granularity=minutes). All timestamps stored as UTC. `save_matches()` does both match upsert and odds history append in one call. Reference data seeding uses upsert to be idempotent.
- **Phase 6a CLI Implementation**: Watch rules CLI uses argparse with subcommands. Observation string format: `"ODDS:MODE:DETAILS"` where MODE is `event` or `continuous`. Example: `"HAD,HHA:event:before_kickoff:30"` means "fetch HAD and HHA odds 30 minutes before kickoff". CLI connects to MongoDB on each invocation (stateless).
- **Odds Types from HKJC API**: Extracted 38 odds type translations from HKJC frontend `LB_FB_TITLE_` labels in `description-en-res.json` and `description-ch-res.json`. Includes standard, corner, goal scorer, extra time, and tournament special odds. Full table in `docs/odds_types.md`.
- **Tournament List API**: HKJC has a separate `tournamentList` GraphQL query (whitelisted, no parameters needed) that returns all available tournaments with ID, code, name_en, name_ch. Stored in `tournaments_ref` collection keyed by tournament ID. Note: same tournament code (e.g., "EPL") can have multiple entries with different IDs (different seasons).
- **Tournament Discovery**: `upsert_tournaments()` in db.py uses `$setOnInsert` for `createdAt` to only set on first insert, and `$set` for all other fields. This means existing tournaments get their names/metadata updated but retain their creation timestamp. Called during each scheduler discovery cycle.
- **Phase 7 Scheduler Implementation**: Two-layer `MatchScheduler` class. Layer 1 (Discovery) runs every `DISCOVERY_INTERVAL_SECONDS`, fetches basic match list, evaluates watch rules, computes absolute trigger times from kickoff + trigger event, and schedules APScheduler jobs. Layer 2 (Fetch) executes at scheduled times: calls API with specific odds types, finds the target match in response, saves to DB. Key design decisions: (1) Dedup via `_scheduled_keys` set prevents duplicate scheduling, (2) Past triggers are silently skipped, (3) Continuous mode adjusts start_time to `now` if already past, (4) fulltime estimated as kickoff + 105min (90min + 15min buffer).
- **Phase 8 Entry Point**: `main.py` uses argparse with `--once` flag. Service mode sets up SIGINT/SIGTERM handlers and blocks on `scheduler.wait()`. Single-fetch mode (`run_once`) collects all odds types across all matched rules, makes one API call with all needed odds types, filters to matched matches, and saves. This minimizes API calls in one-shot mode.
- **Milestone 2 Reached**: Full rule-based pipeline running end-to-end: watch rules -> discovery -> scheduled fetches -> MongoDB storage. Can run as service or single-shot.
- **Phase 10 Docker**: Dockerfile uses multi-step uv install for layer caching (deps first, then source). `docker-compose.yml` uses `mongo:8` with health check — scrapper waits for MongoDB to be healthy before starting. Data persists in `mongodb_data` Docker volume. CLI commands work via `docker compose exec scrapper uv run python -m hkjc_scrapper.cli ...`.
- **Ad-hoc CLI Commands**: Added `list-matches` (browse live matches from API), `fetch-match` (fetch + save specific match odds), `get-match` (query stored match from DB), `get-odds` (query odds history with time filters: `--latest`, `--before-kickoff`, `--all`, `--last N`). Total CLI commands: 10. Total unit tests: 121.
- **Telegram Integration**: `TGMessageClient` wraps Telethon with sync/async interfaces. `TELEGRAM_ENABLED` toggle in Settings. Integrated into: (1) scheduler — discovery notifications when jobs scheduled, fetch notifications when odds saved, (2) CLI — `add-rule`, `enable-rule`, `disable-rule`, `delete-rule`, `fetch-match` send TG notifications, (3) new `send-message` CLI command for custom one-off messages. All sends are fire-and-forget (failures logged, never crash). Uses HTML formatting for structured messages. Session file named via `TELEGRAM_SESSION_NAME` setting. Total CLI commands: 11. Total unit tests: 137.
- **5 Enhancements (2026-03-20)**: Implemented all 5 enhancements from `docs/enhancement_plan.md`. See "5 Enhancements" section in Current Progress for details. Key changes: (1) `notify_error()` added to TGMessageClient for error alerting; (2) `TG_FETCH_INCLUDE_ODDS` config + odds details in fetch notifications; (3) `TG_DISCOVERY_INCLUDE_RULES` config + rule breakdown in discovery notifications; (4) `--time-series/--ts` flag on `get-odds` CLI with change indicators; (5) full TG command bot with inline buttons (`tg_commands.py`), two-phase TGMessageClient init (`start()` method), `/addrule` wizard, all rule management commands. Total unit tests: 206.
- **TGMessageClient two-phase init**: `__init__` no longer auto-starts the background thread. Callers must call `tg.start()` explicitly. `enable_commands(db, api_client)` must be called BEFORE `start()` to enable bot commands. This applies to both `main.py` and `cli.py`.
- **TG Bot Command UX Enhancements (2026-03-21)**: Three improvements based on user testing: (1) `/rules` now shows full rule details — teams, tournaments, odds types, schedule mode/triggers — not just rule names; (2) Buttons indexed with "#1", "#2" etc. for clarity (e.g., "Disable #1", "Delete #2"); (3) `/odds` shows exact fetch timestamp + relative time to kickoff (e.g., "30 min before kickoff"). Helper functions: `_format_rule_detail()` and `_format_relative_to_kickoff()`. Total unit tests: 240.
- **Scheduler Reload Bug (2026-04-06)**: Discovered continuous jobs start immediately after restart instead of waiting for kickoff. Root cause: `_reload_scheduled_jobs()` used `start_date=now` instead of `max(start_time, now)`. Also added timezone-aware datetime guards for MongoDB reload, expired window cleanup, and configurable `APP_TIMEZONE` with `TZFormatter` for HKT log timestamps.
- **Scheduled Jobs Viewer (2026-04-06)**: New `list-jobs` CLI command and `/jobs` TG command to inspect persisted scheduled jobs from `scheduled_jobs` MongoDB collection. Shows front-end ID, type, odds types, trigger/window times in configured timezone. Total CLI commands: 12. Total TG commands: 11. Total unit tests: 253.
