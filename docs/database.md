# HKJCScrapper - MongoDB Database Schema

Database name: configured via `MONGODB_DATABASE` env var (default: `hkjc`).

## Collections Overview

| Collection | Type | Purpose | Upsert Key |
|------------|------|---------|------------|
| `matches_current` | Regular | Latest state of each match | `_id` (match ID) |
| `odds_history` | Time-series | Append-only odds movement log | N/A (insert only) |
| `watch_rules` | Regular | Configurable observation rules | `name` (unique) |
| `odds_types_ref` | Regular | Odds type code translations | `code` |
| `tournaments_ref` | Regular | Tournament metadata from API | `id` (tournament ID) |

---

## matches_current

Upserted on each fetch. Keyed by HKJC match ID (`_id`). Contains the full latest state of a match including odds.

### Indexes

| Index | Fields | Options |
|-------|--------|---------|
| Primary | `_id` (match ID) | unique (default) |
| status | `status` | |
| tournament.code | `tournament.code` | |
| matchDate | `matchDate` | |
| frontEndId | `frontEndId` | unique, sparse |

### Document Structure

```json
{
  "_id": "50062141",
  "id": "50062141",
  "frontEndId": "FB4233",
  "matchDate": "2026-02-22+08:00",
  "kickOffTime": "2026-02-22T22:00:00.000+08:00",
  "status": "SCHEDULED",
  "updateAt": "2026-02-22T12:00:00.000+08:00",
  "sequence": "1.17717...",
  "esIndicatorEnabled": true,
  "isInteractiveServiceAvailable": true,
  "inplayDelay": false,
  "homeTeam": {
    "id": "50002302",
    "name_en": "Nottingham Forest",
    "name_ch": "諾定咸森林"
  },
  "awayTeam": {
    "id": "50001928",
    "name_en": "Liverpool",
    "name_ch": "利物浦"
  },
  "tournament": {
    "id": "50050013",
    "frontEndId": "FB3397",
    "nameProfileId": "50000051",
    "isInteractiveServiceAvailable": true,
    "code": "EPL",
    "name_en": "Eng Premier",
    "name_ch": "英格蘭超級聯賽"
  },
  "venue": null,
  "tvChannels": [
    { "code": "621", "name_en": "Now 621", "name_ch": "Now 621" }
  ],
  "liveEvents": [
    { "id": "61301051", "code": "BETRADAR" }
  ],
  "featureStartTime": "",
  "featureMatchSequence": "",
  "poolInfo": {
    "normalPools": ["HAD", "HHA", "HDC", "HIL", "CHL", "..."],
    "inplayPools": ["HAD", "HHA", "..."],
    "sellingPools": ["HAD", "HHA", "..."],
    "definedPools": ["TTG", "OOE", "..."],
    "ntsInfo": ["4:H", "2:H", "3:A"],
    "entInfo": [],
    "ngsInfo": [
      { "str": "P001", "name_en": "Player Name", "name_ch": "球員名", "instNo": 1 }
    ],
    "agsInfo": [
      { "str": "P001", "name_en": "Player Name", "name_ch": "球員名" }
    ]
  },
  "runningResult": {
    "homeScore": 1,
    "awayScore": 0,
    "corner": 5,
    "homeCorner": 3,
    "awayCorner": 2
  },
  "runningResultExtra": null,
  "adminOperation": null,
  "foPools": [
    {
      "id": "P12345",
      "status": "SELLINGSTARTED",
      "oddsType": "HAD",
      "instNo": 0,
      "inplay": false,
      "name_ch": "主客和",
      "name_en": "HAD",
      "updateAt": "2026-02-22T12:00:00.000+08:00",
      "expectedSuspendDateTime": "",
      "lines": [
        {
          "lineId": "L001",
          "status": "SELLINGSTARTED",
          "condition": null,
          "main": true,
          "combinations": [
            {
              "combId": "C001",
              "str": "H",
              "status": "AVAILABLE",
              "offerEarlySettlement": "N",
              "currentOdds": "2.50",
              "selections": [
                { "selId": "S001", "str": "H", "name_en": "Home", "name_ch": "主" }
              ]
            }
          ]
        }
      ]
    }
  ],
  "fetchedAt": "2026-02-22T14:00:00.000Z"
}
```

### Sample Queries

```javascript
// Find all EPL matches
db.matches_current.find({ "tournament.code": "EPL" })

// Find scheduled matches for a date
db.matches_current.find({ matchDate: "2026-03-10+08:00", status: "SCHEDULED" })

// Find a match by frontEndId
db.matches_current.find({ frontEndId: "FB4233" })

// Find live matches
db.matches_current.find({ status: { $in: ["FIRSTHALF", "SECONDHALF", "HALFTIME"] } })

// Get HAD odds for a specific match
db.matches_current.find(
  { _id: "50062141" },
  { "foPools": { $elemMatch: { oddsType: "HAD" } } }
)

// Find matches by team name (partial, case-insensitive)
db.matches_current.find({
  $or: [
    { "homeTeam.name_en": /liverpool/i },
    { "awayTeam.name_en": /liverpool/i }
  ]
})
```

---

## odds_history

Append-only **time-series collection**. One document per (match, oddsType) per fetch cycle. Used for odds movement analysis.

### Time-Series Configuration

| Option | Value |
|--------|-------|
| `timeField` | `fetchedAt` |
| `metaField` | `matchId` |
| `granularity` | `minutes` |

### Indexes

| Index | Fields | Options |
|-------|--------|---------|
| Compound | `(matchId: 1, oddsType: 1, fetchedAt: -1)` | |

### Document Structure

```json
{
  "matchId": "50062141",
  "matchDescription": "Nottingham Forest vs Liverpool",
  "oddsType": "HAD",
  "inplay": false,
  "lines": [
    {
      "lineId": "L001",
      "status": "SELLINGSTARTED",
      "condition": null,
      "main": true,
      "combinations": [
        {
          "combId": "C001",
          "str": "H",
          "status": "AVAILABLE",
          "offerEarlySettlement": "N",
          "currentOdds": "2.50",
          "selections": [
            { "selId": "S001", "str": "H", "name_en": "Home", "name_ch": "主" }
          ]
        }
      ]
    }
  ],
  "fetchedAt": "2026-02-22T14:00:00.000Z"
}
```

### Sample Queries

```javascript
// All odds history for a match
db.odds_history.find({ matchId: "50062141" }).sort({ fetchedAt: 1 })

// HAD odds movement for a match
db.odds_history.find({ matchId: "50062141", oddsType: "HAD" }).sort({ fetchedAt: 1 })

// Odds snapshots in a time range
db.odds_history.find({
  matchId: "50062141",
  oddsType: "HAD",
  fetchedAt: {
    $gte: ISODate("2026-02-22T19:00:00Z"),
    $lte: ISODate("2026-02-22T22:00:00Z")
  }
}).sort({ fetchedAt: 1 })

// Count snapshots per match per odds type
db.odds_history.aggregate([
  { $group: { _id: { matchId: "$matchId", oddsType: "$oddsType" }, count: { $sum: 1 } } },
  { $sort: { count: -1 } }
])

// Extract home odds over time for a match (HAD, main line, "H" selection)
db.odds_history.find(
  { matchId: "50062141", oddsType: "HAD" },
  { fetchedAt: 1, "lines.combinations.currentOdds": 1, "lines.combinations.str": 1 }
).sort({ fetchedAt: 1 })
```

---

## watch_rules

Configurable observation rules managed via CLI. Each rule specifies what matches to watch, what odds to collect, and when.

### Indexes

| Index | Fields | Options |
|-------|--------|---------|
| name | `name` | unique |

### Document Structure

```json
{
  "_id": ObjectId("..."),
  "name": "La Liga Big 3",
  "enabled": true,
  "match_filter": {
    "teams": ["Barcelona", "Real Madrid", "Atletico Madrid"],
    "tournaments": ["SFL"],
    "match_ids": []
  },
  "observations": [
    {
      "odds_types": ["HAD", "HIL", "HDC"],
      "schedule": {
        "mode": "event",
        "triggers": [
          { "event": "before_kickoff", "minutes": 30 }
        ],
        "interval_seconds": null,
        "start_event": null,
        "end_event": null
      }
    },
    {
      "odds_types": ["CHL"],
      "schedule": {
        "mode": "continuous",
        "triggers": [],
        "interval_seconds": 300,
        "start_event": "kickoff",
        "end_event": "fulltime"
      }
    }
  ],
  "createdAt": "2026-03-08T10:00:00.000Z",
  "updatedAt": "2026-03-08T10:00:00.000Z"
}
```

### Schedule Fields Reference

**Event mode** (`mode: "event"`):

| `triggers[].event` | Meaning |
|---------------------|---------|
| `before_kickoff` | N minutes before kickoff (requires `minutes`) |
| `at_kickoff` | At kickoff time |
| `at_halftime` | At kickoff + 45 min |
| `after_kickoff` | N minutes after kickoff (requires `minutes`) |

**Continuous mode** (`mode: "continuous"`):

| Field | Meaning |
|-------|---------|
| `interval_seconds` | Poll every N seconds |
| `start_event` | `kickoff`, `halftime`, or `fulltime` |
| `end_event` | `kickoff`, `halftime`, or `fulltime` |

### Sample Queries

```javascript
// All active rules
db.watch_rules.find({ enabled: true })

// Rules watching EPL
db.watch_rules.find({ "match_filter.tournaments": "EPL" })

// Rules that fetch HAD odds
db.watch_rules.find({ "observations.odds_types": "HAD" })

// Rules with continuous polling
db.watch_rules.find({ "observations.schedule.mode": "continuous" })
```

---

## odds_types_ref

Reference data for odds type codes. Seeded from HKJC API `LB_FB_TITLE_` labels. 38 entries.

### Document Structure

```json
{
  "_id": ObjectId("..."),
  "code": "HAD",
  "name_en": "Home/Away/Draw",
  "name_ch": "主客和",
  "description": "Standard 1X2 betting",
  "example": ""
}
```

### Sample Queries

```javascript
// List all odds types
db.odds_types_ref.find({}, { code: 1, name_en: 1, name_ch: 1, _id: 0 }).sort({ code: 1 })

// Look up a code
db.odds_types_ref.findOne({ code: "CHL" })

// Find corner-related odds
db.odds_types_ref.find({ name_en: /corner/i })
```

---

## tournaments_ref

Tournament reference data. Auto-fetched from HKJC `tournamentList` GraphQL query and upserted by tournament ID.

Note: The same tournament code (e.g., "EPL") can have multiple entries with different IDs (different seasons).

### Document Structure

```json
{
  "_id": ObjectId("..."),
  "id": "50050013",
  "code": "EPL",
  "frontEndId": "FB3397",
  "nameProfileId": "50000051",
  "isInteractiveServiceAvailable": true,
  "name_en": "Eng Premier",
  "name_ch": "英格蘭超級聯賽",
  "sequence": "12.Eng Premier...",
  "createdAt": "2026-03-08T10:00:00.000Z",
  "updatedAt": "2026-03-08T10:00:00.000Z"
}
```

### Sample Queries

```javascript
// All tournaments sorted by code
db.tournaments_ref.find({}, { code: 1, name_en: 1, name_ch: 1, _id: 0 }).sort({ code: 1 })

// Find by code
db.tournaments_ref.find({ code: "EPL" })

// Find by tournament ID
db.tournaments_ref.findOne({ id: "50050013" })

// Search by name
db.tournaments_ref.find({ name_en: /premier/i })
```

---

## Status / Enum Values

### Match Status (`matches_current.status`)

| Value | Meaning |
|-------|---------|
| `SCHEDULED` | Not yet started |
| `FIRSTHALF` | First half in progress |
| `HALFTIME` | Half-time break |
| `SECONDHALF` | Second half in progress |
| `FULLTIME` | Match completed |

### Pool Status (`foPools[].status`)

| Value | Meaning |
|-------|---------|
| `SELLINGSTARTED` | Accepting bets |
| `SUSPENDED` | Temporarily suspended |
| `PAYOUTSTARTED` | Paying out results |

### Combination Status (`combinations[].status`)

| Value | Meaning |
|-------|---------|
| `AVAILABLE` | Selection is open |
| `WIN` | Selection won |
| `LOSE` | Selection lost |
