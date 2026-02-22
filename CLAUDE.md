# CLAUDE.md - Project Context for AI Agents

## Project Overview

**HKJCScrapper** is a Python bot that automatically fetches football match odds data from the Hong Kong Jockey Club (HKJC) GraphQL API, transforms it into structured Pydantic models, and stores it in MongoDB.

The bot runs as a scheduled service, polling the API at configurable intervals, and maintains both a "current state" collection (upserted) and an append-only "odds history" collection for tracking odds movements over time.

## Tech Stack & Decisions

| Component        | Choice             | Reason                                           |
| ---------------- | ------------------ | ------------------------------------------------ |
| Language         | Python 3.11+       | User preference                                  |
| Package Manager  | uv                 | Fast, modern Python package manager              |
| HTTP Client      | requests (Session) | Simulates browser with required headers           |
| Database         | MongoDB (pymongo)  | Stores nested JSON natively, configurable host    |
| Data Models      | Pydantic v2        | Validation + serialization of API responses       |
| Configuration    | pydantic-settings  | Loads from `.env` file with type-safe defaults    |
| Scheduling       | APScheduler        | Polling loop with configurable interval           |
| Build System     | hatchling          | Specified in pyproject.toml                      |

## Project Structure

```
HKJCScrapper/
├── src/hkjc_scrapper/       # Main package (src layout)
│   ├── __init__.py
│   ├── config.py            # Settings via pydantic-settings + .env
│   ├── client.py            # HKJC GraphQL API client (requests.Session)
│   ├── models.py            # Pydantic data models mirroring API response
│   ├── parser.py            # Raw JSON -> Pydantic model transformation
│   ├── db.py                # MongoDB connection & CRUD operations
│   ├── scheduler.py         # APScheduler polling loop
│   └── main.py              # CLI entry point (--once or service mode)
├── tests/                   # pytest test suite
├── docs/
│   ├── project_plan.md      # Detailed phased plan with verification steps
│   ├── hkjc_api_guide.txt   # Full API guide (Chinese) explaining GraphQL endpoints
│   └── api/
│       └── base_api_sample_response.json  # Real sample response (~125KB)
├── .env.example             # Template for environment variables
├── .gitignore
├── pyproject.toml           # uv/hatchling project config
└── CLAUDE.md                # This file
```

## Key Architecture Decisions

1. **MongoDB with two collections**:
   - `matches_current`: Upserted on each poll (keyed by match ID). Latest state only.
   - `odds_history`: Append-only. One document per (match, oddsType) per fetch cycle. Enables odds movement analysis.

2. **Configurable odds types**: The list of odds types to capture (HAD, HHA, HDC, HIL, etc.) is controlled via the `ODDS_TYPES` environment variable. Default: `["HAD", "HHA", "HDC", "HIL"]`.

3. **Browser simulation**: The HKJC API requires specific headers (User-Agent, Referer: `https://bet.hkjc.com/`, CORS sec-fetch-* headers) and an OPTIONS preflight before POST. The client must replicate this sequence.

4. **src layout**: Package code lives in `src/hkjc_scrapper/` (not top-level). This is configured in `pyproject.toml` under `[tool.hatch.build.targets.wheel]`.

## HKJC API Summary

- **Endpoint**: `https://info.cld.hkjc.com/graphql/base/` (POST)
- **Authentication**: None, but requires browser-like headers
- **Request flow**: OPTIONS preflight -> POST basic match list -> OPTIONS -> POST detailed match list (with odds) -> POST basic match list
- **Response structure**: `{ "data": { "matches": [ ... ] } }`
- **Each match contains**: id, frontEndId, matchDate, kickOffTime, status, homeTeam, awayTeam, tournament, poolInfo, runningResult, foPools (odds data)
- **foPools structure**: Each pool has an `oddsType` (e.g. "HHA"), `lines` (each with a `condition` like "-2.0"), and `combinations` (each with `currentOdds` and `selections`)
- **Full API guide**: `docs/hkjc_api_guide.txt` (Chinese, comprehensive)
- **Sample response**: `docs/api/base_api_sample_response.json`

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
```

## Environment Variables

See `.env.example` for all available config. Key ones:
- `MONGODB_URI` - MongoDB connection string (default: `mongodb://localhost:27017`)
- `MONGODB_DATABASE` - Database name (default: `hkjc`)
- `GRAPHQL_ENDPOINT` - API URL (default: `https://info.cld.hkjc.com/graphql/base/`)
- `POLL_INTERVAL_SECONDS` - Polling frequency (default: `300`)
- `ODDS_TYPES` - JSON array of odds type codes to capture
- `START_INDEX` / `END_INDEX` - Pagination range (default: 1/60)
- `LOG_LEVEL` - Logging level (default: `INFO`)

## Current Progress

**Phase 1 (Project Scaffolding) - COMPLETE**
- uv project initialized with pyproject.toml + hatchling build system
- src layout created with all 8 module files (placeholder content)
- All dependencies installed and importable
- .env.example and .gitignore created

**Phase 2 (Configuration) - NOT STARTED** <-- Start here
- Implement `Settings` class in `src/hkjc_scrapper/config.py`

**Phases 3-10** - See `docs/project_plan.md` for full details and verification steps for each phase.

## Coding Conventions

- **Models**: Use Pydantic v2 `BaseModel` with `model_config = ConfigDict(...)` (not v1 `class Config`)
- **Config**: Use `pydantic-settings` `BaseSettings` with `.env` file loading
- **Imports**: Use the package name `hkjc_scrapper` (e.g. `from hkjc_scrapper.config import Settings`)
- **Entry point**: `uv run python -m hkjc_scrapper.main` (the `__main__` pattern)
- **No over-engineering**: Keep it simple. Only implement what's needed for the current phase.
- **Error handling**: Log and continue on transient API failures; don't crash the polling loop.
- **Fields**: Use snake_case for Python attributes. The API uses camelCase - handle mapping in Pydantic models via aliases or field renaming.
