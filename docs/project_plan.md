# HKJCScrapper - Project Plan

## Overview

A Python bot that periodically fetches football match odds data from the HKJC GraphQL API, transforms it into structured objects, and stores it in MongoDB. Supports both "current state" lookups and historical odds tracking.

---

## Tech Stack

| Component          | Choice                          |
| ------------------ | ------------------------------- |
| Language           | Python 3.11+                    |
| Package Manager    | uv                              |
| HTTP Client        | requests (with Session)         |
| Database           | MongoDB (pymongo / motor)       |
| Configuration      | pydantic-settings + `.env` file |
| Scheduling         | APScheduler (or simple loop)    |
| Logging            | Python built-in `logging`       |

---

## Phase 1 - Project Scaffolding

- [ ] Initialize `uv` project with `pyproject.toml`
- [ ] Create project directory structure:
  ```
  HKJCScrapper/
  ├── src/
  │   └── hkjc_scrapper/
  │       ├── __init__.py
  │       ├── config.py          # Settings & env vars
  │       ├── client.py          # HKJC GraphQL API client
  │       ├── models.py          # Pydantic data models
  │       ├── db.py              # MongoDB connection & operations
  │       ├── parser.py          # API response -> model transformation
  │       ├── scheduler.py       # Polling scheduler
  │       └── main.py            # Entry point
  ├── tests/
  │   ├── __init__.py
  │   ├── test_client.py
  │   ├── test_parser.py
  │   └── test_db.py
  ├── docs/
  │   └── (existing guide + sample response)
  ├── .env.example
  ├── pyproject.toml
  └── README.md
  ```
- [ ] Add core dependencies: `requests`, `pymongo`, `pydantic`, `pydantic-settings`, `apscheduler`
- [ ] Create `.env.example` with placeholder config values

### Verification
```bash
# 1. Check uv project is valid
uv run python -c "print('project ok')"

# 2. Check all dependencies can be imported
uv run python -c "import requests; import pymongo; import pydantic; import pydantic_settings; import apscheduler; print('all imports ok')"

# 3. Check directory structure exists
find src/hkjc_scrapper -name "*.py" | sort
# Should list all module files

# 4. Check .env.example exists
cat .env.example
```

---

## Phase 2 - Configuration (`config.py`)

- [ ] Define settings class using `pydantic-settings`:
  - `MONGODB_URI` (default: `mongodb://localhost:27017`)
  - `MONGODB_DATABASE` (default: `hkjc`)
  - `GRAPHQL_ENDPOINT` (default: `https://info.cld.hkjc.com/graphql/base/`)
  - `POLL_INTERVAL_SECONDS` (default: `300` i.e. 5 min)
  - `ODDS_TYPES` (list, default: `["HAD", "HHA", "HDC", "HIL"]`, configurable)
  - `START_INDEX` / `END_INDEX` for pagination (default: 1 / 60)
  - `LOG_LEVEL` (default: `INFO`)

### Verification
```bash
# 1. Load config with defaults (no .env needed)
uv run python -c "
from hkjc_scrapper.config import Settings
s = Settings()
print(f'MongoDB URI: {s.MONGODB_URI}')
print(f'Endpoint:    {s.GRAPHQL_ENDPOINT}')
print(f'Odds types:  {s.ODDS_TYPES}')
print(f'Poll interval: {s.POLL_INTERVAL_SECONDS}s')
"

# 2. Load config with overridden env vars
MONGODB_URI="mongodb://custom:27017" ODDS_TYPES='["HAD","CRS"]' \
uv run python -c "
from hkjc_scrapper.config import Settings
s = Settings()
assert s.MONGODB_URI == 'mongodb://custom:27017'
assert s.ODDS_TYPES == ['HAD', 'CRS']
print('env override ok')
"
```

---

## Phase 3 - Pydantic Data Models (`models.py`)

Define structured models that mirror the API response, making them easy to validate, serialize, and store.

- [ ] `Team` - id, name_en, name_ch
- [ ] `Tournament` - id, frontEndId, code, name_en, name_ch
- [ ] `RunningResult` - homeScore, awayScore, corner, homeCorner, awayCorner
- [ ] `Selection` - selId, str, name_ch, name_en
- [ ] `Combination` - combId, str, status, offerEarlySettlement, currentOdds, selections
- [ ] `Line` - lineId, status, condition, main, combinations
- [ ] `FoPool` (Fixed Odds Pool) - id, status, oddsType, instNo, inplay, name_ch, name_en, updateAt, expectedSuspendDateTime, lines
- [ ] `PoolInfo` - normalPools, inplayPools, sellingPools, definedPools, ntsInfo, agsInfo (list of player objects)
- [ ] `TvChannel` - code, name_en, name_ch
- [ ] `Match` - id, frontEndId, matchDate, kickOffTime, status, updateAt, esIndicatorEnabled, homeTeam, awayTeam, tournament, venue, tvChannels, poolInfo, runningResult, foPools, etc.

### Verification
```bash
# Parse the sample response through models - all matches should validate without errors
uv run python -c "
import json
from hkjc_scrapper.models import Match

with open('docs/api/base_api_sample_response.json') as f:
    data = json.load(f)

matches = [Match(**m) for m in data['data']['matches']]
print(f'Parsed {len(matches)} matches successfully')
for m in matches[:3]:
    print(f'  {m.frontEndId}: {m.homeTeam.name_en} vs {m.awayTeam.name_en} [{m.status}]')
    print(f'    foPools: {[p.oddsType for p in m.foPools]}')
"
```

---

## Phase 4 - HKJC GraphQL API Client (`client.py`)

- [ ] Create `HKJCGraphQLClient` class with:
  - `requests.Session` pre-configured with required headers:
    - `User-Agent` (Chrome-like)
    - `Referer: https://bet.hkjc.com/`
    - `Content-Type: application/json`
    - CORS-related headers (`sec-fetch-site`, `sec-fetch-mode`, etc.)
  - GraphQL query templates stored as constants (from the guide):
    - `BASIC_MATCH_LIST_QUERY` (allMatchList - no odds)
    - `DETAILED_MATCH_LIST_QUERY` (with foPools/odds)
- [ ] Implement methods:
  - `send_options_preflight()` - send OPTIONS request for CORS
  - `send_basic_match_list_request()` - fetch match list without odds
  - `send_detailed_match_list_request(odds_types, start_index, end_index)` - fetch matches with configurable odds types
  - `simulate_browser_behavior()` - replicate the browser request sequence (OPTIONS -> basic -> OPTIONS -> detailed -> basic)
- [ ] Add error handling: retries, timeouts, HTTP status checks, JSON parse errors
- [ ] Add rate limiting / delay between requests to avoid being blocked

### Verification
```bash
# Fetch live data from HKJC and print raw match count
uv run python -c "
from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.config import Settings

client = HKJCGraphQLClient(Settings())
response = client.fetch_matches()
matches = response['data']['matches']
print(f'Fetched {len(matches)} matches from HKJC API')
for m in matches[:3]:
    print(f'  {m[\"frontEndId\"]}: {m[\"homeTeam\"][\"name_en\"]} vs {m[\"awayTeam\"][\"name_en\"]}')
"
```

---

## Phase 5 - Response Parser (`parser.py`)

- [ ] `parse_matches_response(raw_json: dict) -> list[Match]`
  - Validate and extract `data.matches` from raw API response
  - Convert each match dict into a `Match` pydantic model
  - Handle missing/null fields gracefully (e.g. `venue: null`, `runningResultExtra: null`)
- [ ] `filter_by_odds_types(matches: list[Match], odds_types: list[str]) -> list[Match]`
  - Filter each match's `foPools` to only keep the configured odds types

### Verification
```bash
# End-to-end: fetch live data -> parse into models -> print structured output
uv run python -c "
from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.parser import parse_matches_response, filter_by_odds_types
from hkjc_scrapper.config import Settings

settings = Settings()
client = HKJCGraphQLClient(settings)
raw = client.fetch_matches()
matches = parse_matches_response(raw)
matches = filter_by_odds_types(matches, settings.ODDS_TYPES)
print(f'Parsed {len(matches)} matches')
for m in matches[:2]:
    print(f'\n{m.frontEndId}: {m.homeTeam.name_en} vs {m.awayTeam.name_en}')
    for pool in m.foPools:
        main_line = next((l for l in pool.lines if l.main), None)
        if main_line:
            odds = {c.str: c.currentOdds for c in main_line.combinations}
            print(f'  {pool.oddsType} (line {main_line.condition}): {odds}')
"
# MILESTONE 1: You should see structured match + odds output
```

---

## Phase 6 - MongoDB Storage (`db.py`)

### Collections Design

**`matches_current`** - Latest state of each match (upserted on each poll)
```
{
  _id: <match.id>,
  frontEndId: "FB4342",
  matchDate: ISODate,
  kickOffTime: ISODate,
  status: "SECONDHALF",
  homeTeam: { id, name_en, name_ch },
  awayTeam: { id, name_en, name_ch },
  tournament: { id, code, name_en, name_ch },
  runningResult: { homeScore, awayScore, corner, homeCorner, awayCorner },
  poolInfo: { normalPools: [...], inplayPools: [...], ... },
  foPools: [ ... full odds data ... ],
  updatedAt: ISODate (API's updateAt),
  fetchedAt: ISODate (when we fetched it)
}
```

**`odds_history`** - Append-only snapshots for odds change tracking
```
{
  _id: ObjectId,
  matchId: "50062906",
  matchDescription: "San Diego FC vs CF Montreal",
  oddsType: "HHA",
  inplay: true,
  lines: [ ... snapshot of all lines/combinations at this point ... ],
  fetchedAt: ISODate
}
```

### Implementation

- [ ] `MongoDBClient` class:
  - `__init__(uri, database)` - connect to MongoDB
  - `upsert_match(match: Match)` - insert or update `matches_current`
  - `insert_odds_snapshot(match_id, match_desc, fo_pool)` - append to `odds_history`
  - `save_matches(matches: list[Match])` - batch upsert matches + insert odds snapshots
  - `get_match(match_id)` - retrieve current state
  - `get_odds_history(match_id, odds_type, time_range)` - query historical odds
- [ ] Create indexes:
  - `matches_current`: index on `status`, `tournament.code`, `matchDate`
  - `odds_history`: compound index on `(matchId, oddsType, fetchedAt)`

### Verification
```bash
# 1. Requires MongoDB running. Start with: mongod or docker run -d -p 27017:27017 mongo
# 2. Save sample data to DB and query it back
uv run python -c "
import json
from hkjc_scrapper.models import Match
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.config import Settings

settings = Settings()
db = MongoDBClient(settings.MONGODB_URI, settings.MONGODB_DATABASE)

# Parse sample data
with open('docs/api/base_api_sample_response.json') as f:
    data = json.load(f)
matches = [Match(**m) for m in data['data']['matches']]

# Save to DB
db.save_matches(matches)
print(f'Saved {len(matches)} matches')

# Query back
match = db.get_match(matches[0].id)
print(f'Retrieved: {match[\"homeTeam\"][\"name_en\"]} vs {match[\"awayTeam\"][\"name_en\"]}')

# Check odds history was created
from pymongo import MongoClient
client = MongoClient(settings.MONGODB_URI)
history_count = client[settings.MONGODB_DATABASE]['odds_history'].count_documents({})
print(f'Odds history records: {history_count}')
"
```

---

## Phase 7 - Scheduler (`scheduler.py`)

- [ ] Implement polling loop using APScheduler or `asyncio` loop:
  - On each tick:
    1. Call `client.send_detailed_match_list_request()`
    2. Parse response into `Match` models
    3. Save to MongoDB (upsert current + append history)
    4. Log summary: number of matches fetched, any errors
  - Configurable interval via `POLL_INTERVAL_SECONDS`
- [ ] Graceful shutdown handling (SIGINT/SIGTERM)
- [ ] Error recovery: log and continue on transient failures, don't crash the loop

### Verification
```bash
# Start scheduler, let it run for 2 poll cycles, then Ctrl+C
uv run python -m hkjc_scrapper.main
# Expected: logs showing periodic fetch, parse, save cycle
# Then Ctrl+C should show "Shutting down gracefully..."
```

---

## Phase 8 - Entry Point (`main.py`)

- [ ] CLI entry point that:
  - Loads config from `.env`
  - Initializes the API client, DB client, and scheduler
  - Supports `--once` flag for single fetch (useful for testing/cron)
  - Default mode: starts the scheduled polling service
  - Logs startup info (config summary, DB connection status)

### Verification
```bash
# 1. Single-fetch mode (no MongoDB needed to verify the fetch+parse)
uv run python -m hkjc_scrapper.main --once
# Expected: fetches data, saves to DB, prints summary, exits

# 2. Service mode (requires MongoDB)
uv run python -m hkjc_scrapper.main
# Expected: starts polling loop, logs each cycle
# Ctrl+C to stop

# MILESTONE 2: Full pipeline running end-to-end
```

---

## Phase 9 - Testing

- [ ] Unit tests for `parser.py` using the sample response JSON as fixture
- [ ] Unit tests for `models.py` (validation, edge cases)
- [ ] Integration test for `client.py` (mock HTTP responses)
- [ ] Integration test for `db.py` (use mongomock or test DB)

### Verification
```bash
uv run pytest tests/ -v
# All tests should pass
```

---

## Phase 10 - Polish & Deployment

- [ ] Add `Dockerfile` for containerized deployment
- [ ] Add `docker-compose.yml` with MongoDB + scrapper services
- [ ] Add `.gitignore` (venv, .env, __pycache__, etc.)
- [ ] Verify end-to-end: start service -> fetch data -> verify in MongoDB

### Verification
```bash
# 1. Build and start with docker-compose
docker-compose up --build -d

# 2. Check both containers are running
docker-compose ps
# Expected: both 'mongo' and 'scrapper' services are up

# 3. Check logs
docker-compose logs -f scrapper
# Expected: polling loop running, data being saved

# 4. Verify data in MongoDB
docker-compose exec mongo mongosh hkjc --eval "
  print('matches_current:', db.matches_current.countDocuments({}));
  print('odds_history:', db.odds_history.countDocuments({}));
"
```

---

## Key API Reference (from sample response)

### Match Status Values
- `SCHEDULED` - Not started
- `FIRSTHALF` - First half in progress
- `SECONDHALF` - Second half in progress
- `HALFTIME` - Half time break
- `FULLTIME` - Match ended

### Odds Types (configurable)
| Code  | Name               |
| ----- | ------------------ |
| HAD   | Home/Away/Draw     |
| EHA   | Early HAD          |
| HHA   | Handicap           |
| HDC   | Asian Handicap     |
| HIL   | Hi-Lo (total goals)|
| CHL   | Corner Hi-Lo       |
| CRS   | Correct Score      |
| TTG   | Total Goals        |
| NTS   | Next Team to Score |
| CHD   | Corner HAD         |
| FHA   | First Half HAD     |
| FHL   | First Half Hi-Lo   |
| FHH   | First Half Handicap|
| FCS   | First Correct Score|
| OOE   | Odd/Even           |
| FTS   | First Team to Score|
| FGS   | First Goal Scorer  |
| AGS   | Anytime Goal Scorer|

### Pool/Line Status Values
- `SELLINGSTARTED` - Pool is open for bets
- `SUSPENDED` - Temporarily suspended
- `PAYOUTSTARTED` - Line settled, payout started

### Combination Status Values
- `AVAILABLE` - Can bet on this selection
- `WIN` - This selection won
- `LOSE` - This selection lost

---

## Suggested Implementation Order

Start from Phase 1 and work through sequentially. Phases 2-5 can be partially parallelized (config + models first, then client + parser). Phase 6 (DB) depends on models being ready. Phase 7-8 tie everything together.

The first milestone is **Phase 5 complete**: you can run the client, fetch real data, parse it into typed models, and print structured output. The second milestone is **Phase 8 complete**: data is flowing into MongoDB on a schedule.
