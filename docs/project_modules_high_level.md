# HKJCScrapper - High-Level Project Roadmap

## Vision

A complete system for football betting analytics: crawl HKJC odds and 3rd party match events, analyse patterns with ML, and optionally automate bet placement. The system is split into four independent modules that build on each other.

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐
│  Module I        │     │  Module II       │
│  HKJC Odds       │     │  3rd Party       │
│  Crawler         │     │  Events Crawler  │
│  (odds data)     │     │  (corner kicks,  │
│                  │     │   goals, etc.)   │
└───────┬──────────┘     └───────┬──────────┘
        │                        │
        ▼                        ▼
   ┌─────────────────────────────────────┐
   │          MongoDB (shared)           │
   │  matches_current | odds_history     │
   │  watch_rules     | match_events     │
   └──────────────────┬──────────────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │  Module III             │
         │  ML & Analytics         │
         │  (backtesting,          │
         │   strategy signals)     │
         └────────────┬───────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │  Module IV              │
         │  Bet Placement          │
         │  (Playwright + stealth, │
         │   fully automated)      │
         └────────────────────────┘
```

---

## Module I - HKJC Odds Crawler [IN PROGRESS]

**Goal**: Fetch football match odds from HKJC's GraphQL API and store them in MongoDB, based on configurable watch rules.

**Data source**: HKJC GraphQL API (`https://info.cld.hkjc.com/graphql/base/`)

**Key features**:
- Rule-based observation: configure which matches (by team/tournament), which odds types, and when to fetch (before kickoff, halftime, continuous during match)
- Watch rules stored in MongoDB, managed via CLI
- Two-layer scheduler: periodic discovery of matches + scheduled fetch jobs at computed times
- Two data collections: `matches_current` (latest state, upserted) and `odds_history` (append-only time-series for odds movement tracking)

**Tech stack**: Python 3.11+, uv, requests, pymongo, Pydantic v2, pydantic-settings, APScheduler, MongoDB 8.x

**Status**: Phase 1 (scaffolding) complete. Phase 2 (configuration) next.

**Detailed plan**: See `docs/project_plan.md`

---

## Module II - 3rd Party Football Events Crawler [NOT STARTED]

**Goal**: Capture live match events (corner kicks, goals, cards, substitutions) with timestamps from an external API, and align them with HKJC match data for combined analysis.

**Data source**: TBD — candidates include football-data.org, API-Football, SportMonks, or similar.

**Key features**:
- Crawl live events during matches: corner kicks (with minute), goals, cards, substitutions
- Store events in MongoDB with precise timestamps (minute of match + wall-clock time)
- Align with Module I data using `team name + match date + kickoff time` (timezone-normalized)
- Enable queries like "what were the CHL odds when the 5th corner was taken?"

**Data schema** (preliminary):
```json
{
  "matchId": "<HKJC match ID or cross-reference key>",
  "event_type": "corner_kick",
  "minute": 23,
  "team": "home",
  "timestamp": "ISODate",
  "source": "api-football"
}
```

**Cross-module dependency**: Module I must store enough match metadata (team names, kickoff time, tournament) to enable fuzzy matching with the 3rd party API's match identifiers.

**Match alignment strategy**:
- HKJC uses its own match IDs (e.g. `50062906`) which won't exist in external APIs
- Alignment key: `home team name + away team name + match date + kickoff time`
- Timezone normalization is critical — HKJC uses `+08:00` (Hong Kong time); 3rd party APIs may use UTC
- Team name normalization may be needed (e.g. "Man Utd" vs "Manchester United")

---

## Module III - Machine Learning & Data Analytics [NOT STARTED]

**Goal**: Analyse historical odds and match events to find profitable patterns, build predictive models, and backtest strategies.

**Key features**:
- Time-aligned data joins: correlate odds movements (Module I) with live events (Module II) at any point during a match
- Strategy exploration: identify patterns like "CHL odds drop after 3 consecutive corners in 5 minutes"
- Backtesting framework: replay historical data through strategies to evaluate profitability
- Risk analysis: drawdown, variance, Kelly criterion for stake sizing
- Signal generation: produce actionable recommendations (e.g. "bet CHL High at odds > X when Y condition is met")

**Likely tech stack**: pandas, numpy, scikit-learn, possibly XGBoost/LightGBM. Jupyter notebooks for exploration, Python scripts for production backtests.

**Data requirements from Module I & II**:
- `odds_history` with granular timestamps (time-series collection)
- `match_events` with per-minute event data
- Ability to query: "for match X, give me all odds snapshots and events between minute 20 and minute 45"

**Output**: Signals/recommendations stored in MongoDB (e.g. `signals` collection), consumable by Module IV or by a human.

---

## Module IV - Automated Bet Placement [NOT STARTED]

**Goal**: Automatically place bets on HKJC based on signals generated by Module III.

**Tech stack**: Playwright + `playwright-stealth` (chosen over Selenium for faster execution, better anti-detection, native async support)

**Key features**:
- Fully automated — no human-in-the-loop during execution
- Consume signals from Module III's `signals` collection
- Place bets via HKJC web interface automation
- Safety mechanisms:
  - Re-validate odds before placing (abort if odds moved unfavourably)
  - Handle HKJC bet rejection (odds changed) — re-analyse and retry or skip
  - Configurable stake limits and loss limits
- Bet tracking: record all placed bets with timestamps, odds, stakes, and outcomes
- Post-match settlement: track actual results and P&L

**Important: ToS & legal considerations**:
- HKJC Terms of Service explicitly prohibit automated/bot interactions
- Account suspension is permanent if detected
- Detection vectors: `navigator.webdriver` flag, timing patterns, bet-to-odds-change latency, browser fingerprint
- Mitigation: Playwright stealth patches, randomized delays, human-like mouse movements
- **This module is isolated and optional.** Modules I-III are designed to produce standalone signals a human could act on manually.

---

## Cross-Module Design Decisions

| Decision | Rationale |
|----------|-----------|
| **MongoDB for all modules** | Single database. Nested JSON structure fits HKJC data natively. Time-series collections (v5.0+) handle odds_history volume (~200K docs/day). No need for a separate time-series DB. |
| **Match alignment by team+date+time** | HKJC match IDs are proprietary. Cross-referencing with 3rd party APIs requires fuzzy matching on team names + kickoff time. Timezone normalization (HK +08:00) is mandatory. |
| **Playwright over Selenium** | Faster, native async, better anti-detection with `playwright-stealth`, auto-manages browser binaries. |
| **Watch rules in MongoDB** | Dynamic configuration without restarts. Rules managed via CLI. Enables per-match, per-odds-type, per-timing fetch schedules. |
| **Data retention strategy** | TTL indexes on `odds_history` for automatic expiry (e.g. 6 months). Optional Parquet export for long-term archival / backtesting. |
| **Modules I-III standalone** | Module IV (betting) is isolated and optional. The system produces value without it — signals and analytics can be consumed by a human. |
