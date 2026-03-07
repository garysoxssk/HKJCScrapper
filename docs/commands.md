# HKJCScrapper - Command Reference

## Running the Bot

### Service Mode (default)

Starts the discovery loop and scheduled fetch jobs. Runs until Ctrl+C.

```bash
uv run python -m hkjc_scrapper.main
```

### Single Fetch Mode

Runs one discovery + fetch cycle, then exits. Useful for testing.

```bash
uv run python -m hkjc_scrapper.main --once
```

---

## Watch Rules CLI

### Add a Rule

```bash
# Event mode: fetch HAD, HIL, HDC 30 min before kickoff for La Liga big 3
uv run python -m hkjc_scrapper.cli add-rule \
  --name "La Liga Big 3" \
  --teams "Barcelona,Real Madrid,Atletico Madrid" \
  --tournaments "SFL" \
  --observation "HAD,HIL,HDC:event:before_kickoff:30"

# Event mode: fetch at kickoff (no minutes needed)
uv run python -m hkjc_scrapper.cli add-rule \
  --name "EPL All at Kickoff" \
  --tournaments "EPL" \
  --observation "HAD,HHA:event:at_kickoff"

# Event mode: fetch at halftime
uv run python -m hkjc_scrapper.cli add-rule \
  --name "EPL Halftime" \
  --tournaments "EPL" \
  --observation "HAD:event:at_halftime"

# Continuous mode: poll corners every 5 min during match
uv run python -m hkjc_scrapper.cli add-rule \
  --name "La Liga Corners Live" \
  --tournaments "SFL" \
  --observation "CHL,CHD:continuous:300:kickoff:fulltime"

# Multiple observations on one rule
uv run python -m hkjc_scrapper.cli add-rule \
  --name "EPL Full Coverage" \
  --tournaments "EPL" \
  --observation "HAD,HHA,HDC:event:before_kickoff:30" \
  --observation "CHL:continuous:300:kickoff:fulltime"

# Filter by specific match IDs
uv run python -m hkjc_scrapper.cli add-rule \
  --name "Specific Match" \
  --match-ids "50062141" \
  --observation "HAD:event:at_kickoff"
```

### Observation String Format

```
ODDS_TYPES:MODE:DETAILS

Event mode:     ODDS:event:TRIGGER[:MINUTES]
Continuous mode: ODDS:continuous:INTERVAL_SEC:START_EVENT:END_EVENT
```

**Trigger events**: `before_kickoff`, `at_kickoff`, `at_halftime`, `after_kickoff`

**Event boundaries**: `kickoff`, `halftime`, `fulltime`

### List All Rules

```bash
uv run python -m hkjc_scrapper.cli list-rules
```

### Show Rule Details

```bash
uv run python -m hkjc_scrapper.cli show-rule --name "La Liga Big 3"
```

### Enable / Disable a Rule

```bash
uv run python -m hkjc_scrapper.cli disable-rule --name "La Liga Big 3"
uv run python -m hkjc_scrapper.cli enable-rule --name "La Liga Big 3"
```

### Delete a Rule

```bash
uv run python -m hkjc_scrapper.cli delete-rule --name "La Liga Big 3"
```

---

## Ad-Hoc Data Retrieval

### List Matches

Browse current matches available on HKJC. Shows match ID, front-end ID, tournament, teams, kickoff time, and status.

```bash
# List all matches
uv run python -m hkjc_scrapper.cli list-matches

# Filter by tournament
uv run python -m hkjc_scrapper.cli list-matches --tournament EPL

# Filter by status
uv run python -m hkjc_scrapper.cli list-matches --status SCHEDULED

# Filter by team name (partial match, case-insensitive)
uv run python -m hkjc_scrapper.cli list-matches --team barcelona

# Combine filters
uv run python -m hkjc_scrapper.cli list-matches --tournament SFL --status SCHEDULED
```

Example output:
```
ID           FrontEndId   Tourn    Home                   Away                   Kickoff            Status
--------------------------------------------------------------------------------------------------------------
50062141     FB4233       EPL      Nottingham Forest      Liverpool              2026-02-22 22:00   FIRSTHALF
50062906     FB4342       MLS      San Diego FC           CF Montreal            2026-02-22 11:30   SECONDHALF
```

### Fetch Match Odds

Fetch odds for a specific match and save to MongoDB. Use `list-matches` first to find the match ID.

```bash
# Fetch by match ID (saves to DB by default)
uv run python -m hkjc_scrapper.cli fetch-match --id 50062141 --odds HAD,HHA,HDC

# Fetch by front-end ID
uv run python -m hkjc_scrapper.cli fetch-match --front-end-id FB4233 --odds HAD,HIL

# Preview only (don't save to DB)
uv run python -m hkjc_scrapper.cli fetch-match --id 50062141 --odds HAD --no-save
```

Example output:
```
Match: FB4233 (50062141)
  Nottingham Forest vs Liverpool
  Tournament: Eng Premier (EPL)
  Kickoff: 2026-02-22 22:00
  Status: FIRSTHALF
  Odds pools: 3
    HAD: 1 lines, 3 combinations (SELLINGSTARTED)
      Main: H=2.50 | D=3.20 | A=2.80
    HHA: 2 lines, 6 combinations (SELLINGSTARTED)
      Main [-1.0]: H=1.90 | D=3.40 | A=3.60
    HDC: 2 lines, 4 combinations (SELLINGSTARTED)
      Main [-0.5/-1.0]: H=1.85 | A=2.00

Saved to DB: 1 match, 3 odds snapshots
```

### Typical Workflow

```bash
# Step 1: See what matches are on today
uv run python -m hkjc_scrapper.cli list-matches --status SCHEDULED

# Step 2: Find the EPL match you want
uv run python -m hkjc_scrapper.cli list-matches --tournament EPL

# Step 3: Fetch and store the odds for that match
uv run python -m hkjc_scrapper.cli fetch-match --id 50062141 --odds HAD,HHA,HDC,HIL,CHL
```

---

## One-Time Data Seeding

### Seed Odds Types (38 types with EN/CH translations)

```bash
uv run python -c "
from hkjc_scrapper.config import Settings
from hkjc_scrapper.db import MongoDBClient
from hkjc_scrapper.reference_data import ODDS_TYPES_DATA

settings = Settings()
db = MongoDBClient(settings.MONGODB_URI, settings.MONGODB_DATABASE)
db.ensure_collections()
count = db.seed_odds_types([ot.model_dump() for ot in ODDS_TYPES_DATA])
print(f'Seeded {count} odds types')
db.close()
"
```

### Seed Tournaments from Live API

```bash
uv run python -c "
from hkjc_scrapper.config import Settings
from hkjc_scrapper.client import HKJCGraphQLClient
from hkjc_scrapper.db import MongoDBClient

settings = Settings()
client = HKJCGraphQLClient(settings)
db = MongoDBClient(settings.MONGODB_URI, settings.MONGODB_DATABASE)
db.ensure_collections()
response = client.send_tournament_list_request()
tournaments = response['data']['tournamentList']
result = db.upsert_tournaments(tournaments)
print(f'Tournaments: {result[\"inserted\"]} inserted, {result[\"updated\"]} updated')
db.close()
"
```

---

## Testing

```bash
# Run unit tests only (default, no external deps needed)
uv run pytest

# Run MongoDB integration tests (requires local MongoDB)
uv run pytest -m mongodb

# Run live HKJC API integration tests (requires internet)
uv run pytest -m integration

# Run all tests
uv run pytest -m "integration or mongodb" --override-ini="addopts="

# Run a specific test file
uv run pytest tests/test_scheduler.py -v

# Run with debug output
uv run pytest -v -s
```

---

## Development

```bash
# Install dependencies
uv sync

# Add a new dependency
uv add <package-name>

# Add a dev dependency
uv add --dev <package-name>
```

---

## Environment Variables

Set in `.env` file or as environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGODB_DATABASE` | `hkjc` | Database name |
| `GRAPHQL_ENDPOINT` | `https://info.cld.hkjc.com/graphql/base/` | HKJC API URL |
| `DISCOVERY_INTERVAL_SECONDS` | `900` | How often to discover matches (seconds) |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
