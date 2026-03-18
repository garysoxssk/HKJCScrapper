# HKJCScrapper - Project Plan (Module I)

## Overview

A Python bot that fetches football match odds data from the HKJC GraphQL API based on configurable **watch rules**, transforms it into structured objects, and stores it in MongoDB. Supports both "current state" lookups and historical odds tracking.

The bot uses a **rule-based scheduler**: instead of blindly polling everything, it discovers matches that match your rules (by team, tournament, etc.) and fetches specific odds types at configured times (before kickoff, at halftime, continuously during match, etc.).

---

## Tech Stack

| Component          | Choice                          |
| ------------------ | ------------------------------- |
| Language           | Python 3.11+                    |
| Package Manager    | uv                              |
| HTTP Client        | requests (with Session)         |
| Database           | MongoDB (pymongo)               |
| Data Models        | Pydantic v2                     |
| Configuration      | pydantic-settings + `.env` file |
| Scheduling         | APScheduler                     |
| Build System       | hatchling                       |
| Logging            | Python built-in `logging`       |

---

## Phase 1 - Project Scaffolding [COMPLETE]

- [x] Initialize `uv` project with `pyproject.toml`
- [x] Create project directory structure (src layout)
- [x] Add core dependencies: `requests`, `pymongo`, `pydantic`, `pydantic-settings`, `apscheduler`
- [x] Create `.env.example` with placeholder config values
- [x] Create `.gitignore`

### Verification
```bash
uv run python -c "print('project ok')"
uv run python -c "import requests; import pymongo; import pydantic; import pydantic_settings; import apscheduler; print('all imports ok')"
find src/hkjc_scrapper -name "*.py" | sort
```

---

## Phase 2 - Configuration (`config.py`) [COMPLETE]

- [x] Define `Settings` class using `pydantic-settings`:
  - `MONGODB_URI` (default: `mongodb://localhost:27017`)
  - `MONGODB_DATABASE` (default: `hkjc`)
  - `GRAPHQL_ENDPOINT` (default: `https://info.cld.hkjc.com/graphql/base/`)
  - `DISCOVERY_INTERVAL_SECONDS` (default: `900` i.e. 15 min — how often the discovery job runs)
  - `START_INDEX` / `END_INDEX` for pagination (default: 1 / 60)
  - `LOG_LEVEL` (default: `INFO`)

Note: `POLL_INTERVAL_SECONDS` and `ODDS_TYPES` are no longer global settings — they are now per-rule in watch rules.

### Verification
```bash
# 1. Load config with defaults (no .env needed)
uv run python -c "
from hkjc_scrapper.config import Settings
s = Settings()
print(f'MongoDB URI: {s.MONGODB_URI}')
print(f'Endpoint:    {s.GRAPHQL_ENDPOINT}')
print(f'Discovery interval: {s.DISCOVERY_INTERVAL_SECONDS}s')
"

# 2. Load config with overridden env vars
MONGODB_URI='mongodb://custom:27017' \
uv run python -c "
from hkjc_scrapper.config import Settings
s = Settings()
assert s.MONGODB_URI == 'mongodb://custom:27017'
print('env override ok')
"
```

---

## Phase 3 - Pydantic Data Models (`models.py`) [COMPLETE]

Define structured models that mirror the API response.

- [x] `Team` - id, name_en, name_ch
- [x] `Tournament` - id, frontEndId, code, name_en, name_ch
- [x] `RunningResult` - homeScore, awayScore, corner, homeCorner, awayCorner
- [x] `Selection` - selId, str, name_ch, name_en
- [x] `Combination` - combId, str, status, offerEarlySettlement, currentOdds, selections
- [x] `Line` - lineId, status, condition, main, combinations
- [x] `FoPool` (Fixed Odds Pool) - id, status, oddsType, instNo, inplay, name_ch, name_en, updateAt, expectedSuspendDateTime, lines
- [x] `PoolInfo` - normalPools, inplayPools, sellingPools, definedPools, ntsInfo, entInfo, ngsInfo, agsInfo
- [x] `TvChannel` - code, name_en, name_ch
- [x] `Venue` - code, name_en, name_ch
- [x] `LiveEvent` - id, code
- [x] `NgsInfo`, `AgsInfo` - goal scorer info
- [x] `Remark`, `AdminOperation` - admin fields
- [x] `Match` - id, frontEndId, matchDate, kickOffTime, status, updateAt, esIndicatorEnabled, homeTeam, awayTeam, tournament, venue, tvChannels, liveEvents, poolInfo, runningResult, runningResultExtra, adminOperation, foPools, etc.
- [x] `WatchRule` - name, enabled, match_filter, observations (for watch rules — see Phase 6a)
- [x] `MatchFilter` - teams, tournaments, match_ids
- [x] `Observation` - odds_types, schedule
- [x] `Schedule` - mode (event/continuous), triggers, interval_seconds, start_event, end_event

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

## Phase 4 - HKJC GraphQL API Client (`client.py`) [COMPLETE]

- [x] Create `HKJCGraphQLClient` class with:
  - `requests.Session` pre-configured with required headers:
    - `User-Agent` (Chrome-like)
    - `Referer: https://bet.hkjc.com/`
    - `Content-Type: application/json`
    - CORS-related headers (`sec-fetch-site`, `sec-fetch-mode`, etc.)
  - GraphQL query templates stored as constants (from the guide):
    - `BASIC_MATCH_LIST_QUERY` (allMatchList - no odds)
    - `DETAILED_MATCH_LIST_QUERY` (with foPools/odds)
- [x] Implement methods:
  - `send_options_preflight()` - send OPTIONS request for CORS
  - `send_basic_match_list_request()` - fetch match list without odds
  - `send_detailed_match_list_request(odds_types, start_index, end_index)` - fetch matches with configurable odds types
  - `fetch_matches_for_odds(odds_types)` - full sequence (preflight + query) for specific odds types
- [x] Add error handling: retries, timeouts, HTTP status checks, JSON parse errors
- [x] Add rate limiting / delay between requests to avoid being blocked
- [x] **CRITICAL**: Use whitelisted query format (all 13 parameters defined, even if null). See `resources/single-match-req-1.txt`

### Verification
```bash
# Fetch live data from HKJC and print raw match count
uv run python -c "
from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.config import Settings

client = HKJCGraphQLClient(Settings())
response = client.fetch_matches_for_odds(['HAD', 'HHA'])
matches = response['data']['matches']
print(f'Fetched {len(matches)} matches from HKJC API')
for m in matches[:3]:
    print(f'  {m[\"frontEndId\"]}: {m[\"homeTeam\"][\"name_en\"]} vs {m[\"awayTeam\"][\"name_en\"]}')
"
```

---

## Phase 5 - Response Parser (`parser.py`) [COMPLETE]

- [x] `parse_matches_response(raw_json: dict) -> list[Match]`
  - Validate and extract `data.matches` from raw API response
  - Handle missing/null fields gracefully (e.g. `venue: null`, `runningResultExtra: null`)
- [x] `filter_matches_by_rule(matches: list[Match], rule: WatchRule) -> list[Match]`
  - Filter matches by team names, tournament codes, or specific match IDs
- [x] `filter_fopools_by_odds_types(matches: list[Match], odds_types: list[str]) -> list[Match]`
  - Filter each match's `foPools` to only keep the requested odds types
- [x] `get_match_description(match: Match) -> str` - Human-readable description

### Verification
```bash
# End-to-end: fetch live data -> parse into models -> print structured output
uv run python -c "
from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.parser import parse_matches_response, filter_fopools_by_odds_types
from hkjc_scrapper.config import Settings

settings = Settings()
client = HKJCGraphQLClient(settings)
raw = client.fetch_matches_for_odds(['HAD', 'HHA', 'CHL'])
matches = parse_matches_response(raw)
matches = filter_fopools_by_odds_types(matches, ['HAD', 'HHA', 'CHL'])
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

## Phase 6 - MongoDB Storage (`db.py`) [COMPLETE]

### Collections Design

**`matches_current`** - Latest state of each match (upserted on each poll)
```json
{
  "_id": "<match.id>",
  "frontEndId": "FB4342",
  "matchDate": "ISODate",
  "kickOffTime": "ISODate",
  "status": "SECONDHALF",
  "homeTeam": { "id": "...", "name_en": "...", "name_ch": "..." },
  "awayTeam": { "id": "...", "name_en": "...", "name_ch": "..." },
  "tournament": { "id": "...", "code": "MLS", "name_en": "...", "name_ch": "..." },
  "runningResult": { "homeScore": 2, "awayScore": 1, "corner": 5 },
  "foPools": [ "..." ],
  "updatedAt": "ISODate (API's updateAt)",
  "fetchedAt": "ISODate (when we fetched it)"
}
```

**`odds_history`** - Append-only time-series collection for odds change tracking
```json
{
  "_id": "ObjectId",
  "matchId": "50062906",
  "matchDescription": "San Diego FC vs CF Montreal",
  "oddsType": "HHA",
  "inplay": true,
  "lines": [ "...snapshot of all lines/combinations..." ],
  "fetchedAt": "ISODate"
}
```
Created as a MongoDB time-series collection with `timeField: "fetchedAt"`, `metaField: "matchId"`.

**`watch_rules`** - Configurable rules for what to observe
```json
{
  "_id": "ObjectId",
  "name": "Man Utd EPL",
  "enabled": true,
  "match_filter": {
    "teams": ["Manchester United"],
    "tournaments": ["EPL"],
    "match_ids": []
  },
  "observations": [
    {
      "odds_types": ["HAD", "HHA", "HDC"],
      "schedule": {
        "mode": "event",
        "triggers": [
          { "event": "before_kickoff", "minutes": 30 }
        ]
      }
    },
    {
      "odds_types": ["CHL"],
      "schedule": {
        "mode": "continuous",
        "interval_seconds": 300,
        "start_event": "kickoff",
        "end_event": "fulltime"
      }
    }
  ]
}
```

### Schedule trigger types

| Trigger | Meaning | Example |
|---------|---------|---------|
| `before_kickoff` | N minutes before scheduled kickoff | `{"event": "before_kickoff", "minutes": 30}` |
| `at_kickoff` | At kickoff time | `{"event": "at_kickoff"}` |
| `at_halftime` | Kickoff + 45 minutes | `{"event": "at_halftime"}` |
| `after_kickoff` | N minutes after kickoff | `{"event": "after_kickoff", "minutes": 60}` |
| `continuous` | Repeating interval in a time window | `{"mode": "continuous", "interval_seconds": 300, "start_event": "kickoff", "end_event": "fulltime"}` |

### Implementation

- [x] `MongoDBClient` class:
  - `__init__(uri, database)` - connect to MongoDB
  - `ensure_collections()` - create time-series collection for `odds_history`, indexes
  - `upsert_match(match: Match)` - insert or update `matches_current`
  - `insert_odds_snapshot(match_id, match_desc, fo_pool)` - append to `odds_history`
  - `save_matches(matches: list[Match])` - batch upsert matches + insert odds snapshots
  - `get_match(match_id)` - retrieve current state
  - `get_odds_history(match_id, odds_type, time_range)` - query historical odds
  - `seed_reference_data(odds_types, tournaments)` - seed reference collections
  - **Watch rules CRUD**:
    - `add_watch_rule(rule: WatchRule)`
    - `get_active_watch_rules() -> list[WatchRule]`
    - `get_all_watch_rules()` / `get_watch_rule(name)`
    - `update_watch_rule(name, updates)`
    - `enable_watch_rule(name)` / `disable_watch_rule(name)`
    - `delete_watch_rule(name)`
- [x] Create indexes:
  - `matches_current`: index on `status`, `tournament.code`, `matchDate`, `frontEndId` (unique)
  - `odds_history`: compound index on `(matchId, oddsType, fetchedAt)`
  - `watch_rules`: unique index on `name`

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

## Phase 6a - Watch Rules CLI (`cli.py`) [COMPLETE]

- [x] CLI tool for managing watch rules in MongoDB:
  - `add-rule` - add a new watch rule with observation specs
  - `list-rules` - list all rules (with enabled/disabled status)
  - `show-rule` - display full rule details
  - `enable-rule` / `disable-rule` - toggle a rule
  - `delete-rule` - remove a rule
  - Observation string parser for event/continuous modes

### Example usage
```bash
# Add a rule: observe Man Utd EPL matches, HAD before kickoff, CHL continuously
uv run python -m hkjc_scrapper.cli add-rule \
  --name "Man Utd EPL" \
  --teams "Manchester United" \
  --tournaments "EPL" \
  --observation "HAD,HHA,HDC:event:before_kickoff:30" \
  --observation "CHL:continuous:300:kickoff:fulltime"

# Add a rule: all La Liga corner odds, continuous during match
uv run python -m hkjc_scrapper.cli add-rule \
  --name "La Liga Corners" \
  --tournaments "LLG" \
  --observation "CHL:event:before_kickoff:30" \
  --observation "CHL:event:at_halftime"

# List all rules
uv run python -m hkjc_scrapper.cli list-rules

# Disable a rule
uv run python -m hkjc_scrapper.cli disable-rule --name "La Liga Corners"
```

### Verification
```bash
# Add a test rule, list it, disable it, verify
uv run python -m hkjc_scrapper.cli add-rule \
  --name "Test Rule" \
  --tournaments "EPL" \
  --observation "HAD:event:before_kickoff:30"
uv run python -m hkjc_scrapper.cli list-rules
uv run python -m hkjc_scrapper.cli disable-rule --name "Test Rule"
uv run python -m hkjc_scrapper.cli list-rules
# Should show "Test Rule" as disabled
uv run python -m hkjc_scrapper.cli delete-rule --name "Test Rule"
```

---

## Phase 7 - Rule-Based Scheduler (`scheduler.py`) [COMPLETE]

The scheduler has **two layers**:

### Layer 1: Discovery Job (periodic)
Runs every `DISCOVERY_INTERVAL_SECONDS` (default 15 min):
1. Fetch basic match list from HKJC (no odds — lightweight)
2. Load all enabled watch rules from MongoDB
3. Match each rule's filters against available matches
4. For each matched (match, observation), calculate absolute fetch times based on the schedule triggers and the match's `kickOffTime`
5. Schedule/update APScheduler jobs for each calculated fetch time
6. Also refreshes tournament reference data via `tournamentList` API

### Layer 2: Fetch Jobs (scheduled at computed times)
- **Event mode**: One-shot APScheduler `date` trigger at the computed time
  - e.g., "fetch HAD for match FB4342 at 2026-02-22T19:30 (30 min before kickoff)"
- **Continuous mode**: APScheduler `interval` trigger between start and end times
  - e.g., "fetch CHL for match FB4342 every 300s from kickoff until fulltime"

### Implementation
- [x] `MatchScheduler` class:
  - `__init__(client, db, settings)` - initialize with dependencies
  - `start()` - start the discovery job loop
  - `stop()` - graceful shutdown
  - `run_discovery()` - Layer 1 logic (fetch matches, evaluate rules, schedule jobs)
  - `_schedule_observation(match, obs, now)` - schedule event/continuous fetch jobs
  - `execute_fetch(match_id, front_end_id, odds_types)` - Layer 2: call API, parse, save
  - `run_once()` - single discovery + fetch cycle (no scheduling loop)
- [x] Helper functions: `parse_kickoff_time()`, `compute_trigger_time()`, `compute_event_boundary()`
- [x] Deduplication: avoid scheduling duplicate jobs for the same (match, oddsType, time)
- [x] Graceful shutdown handling (SIGINT/SIGTERM)
- [x] Error recovery: log and continue on transient failures
- [x] Tournament discovery during each cycle

### Verification
```bash
# 1. Add a watch rule first
uv run python -m hkjc_scrapper.cli add-rule \
  --name "All EPL" --tournaments "EPL" \
  --observation "HAD,HHA:event:before_kickoff:30"

# 2. Start the scheduler — it should discover matches and schedule fetches
uv run python -m hkjc_scrapper.main
# Expected log output:
#   [Discovery] Found 45 matches from HKJC
#   [Discovery] Rule "All EPL" matched 8 matches
#   [Scheduler] Scheduled HAD,HHA fetch for FB4342 at 2026-02-22T19:30
#   [Scheduler] Scheduled HAD,HHA fetch for FB4343 at 2026-02-22T20:00
#   ...

# 3. Ctrl+C should show "Shutting down gracefully..."
```

---

## Phase 8 - Entry Point (`main.py`) [COMPLETE]

- [x] CLI entry point that:
  - Loads config from `.env`
  - Initializes the API client, DB client, and scheduler
  - Supports `--once` flag for single fetch of all rule-matched matches (useful for testing)
  - Default mode: starts the discovery + scheduler loop
  - Logs startup info (config summary, DB connection status, active rule count)
- [x] `__main__.py` for `python -m hkjc_scrapper` support
- [x] Structured logging with configurable level

### Verification
```bash
# 1. Single-fetch mode
uv run python -m hkjc_scrapper.main --once
# Expected: discovers matches, evaluates rules, fetches matching odds, saves, exits

# 2. Service mode (requires MongoDB)
uv run python -m hkjc_scrapper.main
# Expected: starts discovery loop, schedules fetches, runs them on time
# Ctrl+C to stop

# MILESTONE 2: Full rule-based pipeline running end-to-end
```

---

## Phase 9 - Testing

- [ ] Unit tests for `parser.py` using the sample response JSON as fixture
- [ ] Unit tests for `models.py` (validation, edge cases, WatchRule model)
- [ ] Unit tests for scheduler rule evaluation (given rules + matches, verify correct schedule)
- [ ] Integration test for `client.py` (mock HTTP responses)
- [ ] Integration test for `db.py` (use mongomock or test DB)
- [ ] Integration test for `cli.py` (add/list/disable/delete rules)

### Verification
```bash
uv run pytest tests/ -v
# All tests should pass
```

---

## Phase 10 - Polish & Deployment [COMPLETE]

- [x] Add `Dockerfile` for containerized deployment
- [x] Add `docker-compose.yml` with MongoDB + scrapper services
- [x] Verify end-to-end: start service -> rules evaluated -> data fetched on schedule -> verify in MongoDB

### Verification
```bash
# 1. Build and start with docker-compose
docker compose up -d

# 2. Check both containers are running
docker compose ps

# 3. Check logs
docker compose logs -f scrapper
# Expected: discovery loop running, fetch jobs executing on schedule

# 4. Verify data in MongoDB
docker compose exec mongodb mongosh hkjc --quiet --eval "
  print('matches_current:', db.matches_current.countDocuments({}));
  print('odds_history:', db.odds_history.countDocuments({}));
  print('watch_rules:', db.watch_rules.countDocuments({}));
  print('tournaments_ref:', db.tournaments_ref.countDocuments({}));
"
```

---

## Project Structure (updated)

```
HKJCScrapper/
├── src/hkjc_scrapper/
│   ├── __init__.py
│   ├── __main__.py          # python -m hkjc_scrapper support
│   ├── config.py            # Settings via pydantic-settings + .env
│   ├── client.py            # HKJC GraphQL API client (requests.Session)
│   ├── models.py            # Pydantic models (API response + WatchRule)
│   ├── parser.py            # Raw JSON -> Pydantic model transformation
│   ├── db.py                # MongoDB connection & CRUD (matches, odds, rules)
│   ├── cli.py               # CLI for managing watch rules + ad-hoc queries
│   ├── scheduler.py         # Rule-based scheduler (discovery + fetch jobs)
│   ├── reference_data.py    # Seed data for odds types and tournaments
│   └── main.py              # Entry point (--once or service mode)
├── tests/
├── docs/
│   ├── project_tracker.md   # High-level 4-module roadmap
│   ├── project_plan.md      # This file
│   ├── commands.md           # CLI command reference
│   ├── database.md           # MongoDB schema documentation
│   ├── odds_types.md         # Odds type reference table
│   ├── hkjc_api_guide.txt   # Full API guide (Chinese)
│   └── api/
│       └── base_api_sample_response.json
├── Dockerfile               # Production Docker image
├── docker-compose.yml       # MongoDB + scrapper orchestration
├── .dockerignore
├── .env.example
├── .gitignore
├── pyproject.toml
└── CLAUDE.md
```

---

## Key API Reference

### Match Status Values
- `SCHEDULED` - Not started
- `FIRSTHALF` - First half in progress
- `SECONDHALF` - Second half in progress
- `HALFTIME` - Half time break
- `FULLTIME` - Match ended

### Odds Types (configurable per watch rule)
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

### HKJC Tournament Codes (common)
| Code  | League                    |
| ----- | ------------------------- |
| EPL   | English Premier League    |
| LLG   | Spanish La Liga           |
| ITA   | Italian Serie A           |
| BUN   | German Bundesliga         |
| FRA   | French Ligue 1            |
| UCL   | UEFA Champions League     |
| UEL   | UEFA Europa League        |
| MLS   | US Major League           |

### Pool/Line Status Values
- `SELLINGSTARTED` - Pool is open for bets
- `SUSPENDED` - Temporarily suspended
- `PAYOUTSTARTED` - Line settled, payout started

### Combination Status Values
- `AVAILABLE` - Can bet on this selection
- `WIN` - This selection won
- `LOSE` - This selection lost

---

## Milestones

| Milestone | Phase | What you can do |
|-----------|-------|-----------------|
| **M1** | Phase 5 | Fetch live data, parse into typed models, print structured output |
| **M2** | Phase 8 | Full rule-based pipeline: rules -> discovery -> scheduled fetches -> MongoDB |
| **M3** | Phase 10 | Dockerized deployment with MongoDB |
