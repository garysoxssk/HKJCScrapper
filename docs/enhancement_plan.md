# Enhancement Plan: 5 Features for HKJCScrapper

## Context

The HKJC Scrapper (Module I) is feature-complete through Milestone 2: rule-based odds fetching, MongoDB storage, scheduling, CLI, and Telegram notifications (send-only). The user wants 5 enhancements to improve observability, configurability, and remote control. The biggest change is making the Telegram bot interactive (bidirectional) with **inline keyboard buttons** so users can issue commands without SSH/CLI access.

### User Decisions (from Q&A)
- **Enhancement 1**: Add optional `--limit N` flag, default = show all snapshots
- **Enhancement 2**: Show **ALL lines** (not just main line) in odds detail messages
- **Enhancement 4 /fetch**: Full fetch + save to DB (same as CLI `fetch-match`)
- **Enhancement 4 /addrule**: Include it, but use **inline keyboard buttons** to guide users through option selection (not raw text input)
- **Enhancement 4 UX**: ALL commands should use inline buttons where applicable (e.g., `/deleterule` shows existing rules as buttons; `/addrule` walks through tournament selection, odds type picking, schedule mode, etc.)

---

## Implementation Order: 5 → 2 → 3 → 1 → 4

| # | Enhancement | Complexity | Rationale for order |
|---|-------------|-----------|-------------------|
| 5 | Error notifications via TG | Small | Zero dependencies, immediate operational value |
| 2 | Odds details in fetch TG message | Small | Config + message formatting only |
| 3 | Rule details in discovery TG message | Small | Same pattern as #2 |
| 1 | CLI time-series odds reader | Medium | Standalone CLI feature, no TG changes |
| 4 | TG bot command listener | Large | Touches thread model, benefits from all other features being done |

---

## Enhancement 5: Error Notification via Telegram ✅ IMPLEMENTED

**Problem**: When scheduled jobs fail (API timeout, MongoDB down), errors are only logged. The user has no visibility unless they check logs.

**Solution**: Add `notify_error()` to TGMessageClient. Call it from scheduler catch blocks.

### Changes

**`src/hkjc_scrapper/tg_msg_client.py`** — add method:
```python
def notify_error(self, context: str, error: Exception) -> None:
    """Notify about an error during a scheduled operation."""
    # Truncate error message to keep TG message readable
    error_str = str(error)
    if len(error_str) > 200:
        error_str = error_str[:200] + "..."
    msg = (
        f"<b>Error</b>: {context}\n"
        f"<code>{error_str}</code>"
    )
    self.send_sync(msg)
```

**`src/hkjc_scrapper/scheduler.py`** — modify 2 catch blocks:

1. `run_discovery()` (line 246): Change `except Exception:` → `except Exception as e:`, add:
   ```python
   if self.tg:
       self.tg.notify_error("Discovery cycle", e)
   ```

2. `execute_fetch()` (line 462): Change `except Exception:` → `except Exception as e:`, add:
   ```python
   if self.tg:
       self.tg.notify_error(f"Fetch {front_end_id}", e)
   ```

**Tests**:
- `tests/test_tg_msg_client.py`: Add `test_notify_error` and `test_notify_error_truncation`
- `tests/test_scheduler.py`: Add tests verifying `tg.notify_error` is called when `execute_fetch` / `run_discovery` raise

---

## Enhancement 2: Configurable Odds Details in "Odds Fetched" Message ✅ IMPLEMENTED

**Problem**: The "Odds Fetched" TG message only shows match name + snapshot count, not the actual odds values. User wants the option to see odds inline.

**Solution**: New config toggle. When enabled, `notify_fetch()` includes **all lines** (not just main) for each pool.

### Changes

**`src/hkjc_scrapper/config.py`** — add:
```python
TG_FETCH_INCLUDE_ODDS: bool = False
```

**`src/hkjc_scrapper/tg_msg_client.py`** — modify `notify_fetch()`:
- Add parameter `odds_details: list[dict] | None = None`
- Each dict represents one pool: `{"oddsType": "HAD", "lines": [{"condition": None, "main": True, "combinations": [{"str": "H", "currentOdds": "2.50"}, ...]}, ...]}`
- When provided, append formatted odds block showing ALL lines per pool:
  ```
  <b>HAD</b>:
    H=2.50 | D=3.20 | A=2.80
  <b>HHA</b>:
    [-1.5] H=1.85 | A=1.95 (main)
    [-2.0] H=2.10 | A=1.70
  ```
- Add helper `_format_pool_odds(detail: dict) -> str` to format one pool's lines
- Truncate message if total length exceeds ~3500 chars (Telegram 4096 limit minus header)

**`src/hkjc_scrapper/scheduler.py`** — in `execute_fetch()` (around line 453):
- When `self.settings.TG_FETCH_INCLUDE_ODDS` is True, extract all line odds from `target.foPools`
- Add helper `_extract_odds_details(foPools: list) -> list[dict]` that extracts all lines from each pool
- Pass result to `notify_fetch(..., odds_details=details)`

**`src/hkjc_scrapper/cli.py`** — in `cmd_fetch_match()`: same pattern, pass odds details when config enabled.

**Tests**:
- `tests/test_tg_msg_client.py`: Test `notify_fetch` with/without `odds_details`, test truncation for large payloads

---

## Enhancement 3: Configurable Rule Details in Discovery/Rule Messages ✅ IMPLEMENTED

**Problem**: Discovery message shows "3 rules, 5 jobs" but doesn't say which rules matched or what was scheduled.

**Solution**: New config toggle. When enabled, include rule-level breakdown.

### Changes

**`src/hkjc_scrapper/config.py`** — add:
```python
TG_DISCOVERY_INCLUDE_RULES: bool = False
```

**`src/hkjc_scrapper/tg_msg_client.py`** — modify `notify_discovery()`:
- Add parameter `rule_details: list[dict] | None = None`
- Each dict: `{"name": "EPL HAD", "matched": 3, "jobs": 5}`
- When provided, append:
  ```
  Rules matched:
  • EPL HAD: 3 matches, 5 jobs
  • La Liga CHL: 2 matches, 2 jobs
  ```

**`src/hkjc_scrapper/scheduler.py`** — in `run_discovery()`:
- Accumulate per-rule stats during the rule evaluation loop (lines 218-233)
- Track: `rule_details = []`, for each rule append `{"name": rule.name, "matched": len(matched), "jobs": count}`
- Pass to `notify_discovery()` when `settings.TG_DISCOVERY_INCLUDE_RULES` is True

**Tests**:
- `tests/test_tg_msg_client.py`: Test `notify_discovery` with/without `rule_details`

---

## Enhancement 1: CLI Time-Series Odds Reader ✅ IMPLEMENTED

**Problem**: `get-odds --all` shows a flat table of all snapshots. User wants a dedicated time-series view that highlights odds movements (changes between snapshots) for a specific odds type.

**Solution**: New `--time-series` / `--ts` flag on `get-odds`. Requires `--odds` (single type). Shows progression with change indicators.

### Output Format
```
CHL Time Series for FB4233 (Man Utd vs Liverpool)
================================================
Time (UTC)              Line    High    Low     Status
2026-03-01 19:30:00     [8.5]   1.75    1.95    SELLING
2026-03-01 19:45:00     [8.5]   1.80v   1.90^   SELLING
2026-03-01 20:00:00     [9.0]*  1.85    1.85    SELLING  (* line changed)
------------------------------------------------
Snapshots: 3 | Range: 30min | Movements: 3
```
- `v` = odds decreased (went down), `^` = odds increased (went up)
- `*` after line condition = line changed from previous snapshot
- Summary at bottom: count, time range, total movements

### Changes

**`src/hkjc_scrapper/cli.py`**:

1. In `build_parser()`:
   - Add `--time-series` / `--ts` flag to get-odds subparser (mutually exclusive with `--all`, `--latest`, etc.)
   - Add `--limit N` optional flag (default: None = show all). Only applies when `--time-series` is active.

2. In `cmd_get_odds()`: add branch for `args.time_series`:
   - Validate `--odds` is provided (required for time-series)
   - Fetch all snapshots: `db.get_odds_history(match_id, odds_type=odds_type_filter)`
   - If `args.limit` is set, slice to last N snapshots
   - Call `_print_odds_time_series(snapshots, odds_type, match_info)`

3. New function `_print_odds_time_series(snapshots, odds_type, match_info)`:
   - Iterate snapshots in order (already sorted ascending by fetchedAt)
   - For each snapshot, extract main line: condition + combination odds
   - Compare with previous snapshot to detect changes
   - Build column headers dynamically from combination `str` values (e.g., H/A/D, High/Low)
   - Print with change indicators
   - Print summary line at end

**Tests**:
- `tests/test_cli.py`: Test `_print_odds_time_series` with mock snapshots showing movements, line changes, and edge cases (single snapshot, no main line, with --limit)

---

## Enhancement 4: Telegram Bot Command Listener with Inline Buttons ✅ IMPLEMENTED

**Problem**: Currently the bot only sends messages. Users want to interact remotely — list matches, fetch odds, manage rules — without CLI/SSH access.

**Solution**: Register Telethon event handlers for incoming commands. Use **inline keyboard buttons** (`Button.inline()`) for interactive guided flows instead of requiring users to type exact arguments. Refactor the background thread to use `run_until_disconnected()` instead of sleep-polling.

### Telethon Inline Button Architecture

Telethon supports two types of interactivity:
1. **`events.NewMessage(pattern='/cmd')`** — handles text commands (e.g., `/help`, `/status`)
2. **`events.CallbackQuery(data=...)`** — handles inline button clicks

**How it works**:
```python
from telethon import Button, events

# Send a message with inline buttons
await event.reply("Select a rule to delete:", buttons=[
    [Button.inline("EPL HAD Rule", data=b"del:EPL HAD Rule")],
    [Button.inline("La Liga CHL", data=b"del:La Liga CHL")],
    [Button.inline("Cancel", data=b"del:cancel")],
])

# Handle button clicks
@client.on(events.CallbackQuery(pattern=b"del:"))
async def handle_delete_callback(event):
    rule_name = event.data.decode().split(":", 1)[1]
    if rule_name == "cancel":
        await event.answer("Cancelled")
        return
    # ... delete the rule ...
    await event.answer(f"Deleted: {rule_name}")
    await event.edit(f"Rule <b>{rule_name}</b> deleted.")
```

**Constraints**:
- `Button.inline(text, data)` — `data` is max **64 bytes**. Use short prefixes like `del:`, `fetch:`, `odds:`.
- `event.answer()` — dismisses the "loading" indicator on the button (required)
- `event.edit()` — edits the original message (replaces buttons with result)
- Buttons arranged in rows: `[[btn1, btn2], [btn3]]` = 2 rows

### Architecture Change

**Current flow** (send-only):
```
Background thread: event loop → _async_init() → while not shutdown: sleep(0.1)
Main thread: send_sync() → run_coroutine_threadsafe(send_message_async)
```

**New flow** (bidirectional):
```
Background thread: event loop → _async_init() → register_handlers() → client.run_until_disconnected()
Main thread: send_sync() → run_coroutine_threadsafe(send_message_async)  [unchanged]
Incoming TG msgs → Telethon dispatches to NewMessage handlers in background thread
Button clicks → Telethon dispatches to CallbackQuery handlers in background thread
Shutdown: main thread calls client.disconnect() → run_until_disconnected() returns → thread exits
```

### Commands with Interactive Flows

| Command | Initial Response | Inline Buttons |
|---------|-----------------|----------------|
| `/help` | List of all commands | None (text only) |
| `/status` | Bot status (uptime, jobs, rules) | None (text only) |
| `/matches` | "Select tournament:" | Buttons for each tournament with active matches → then shows match list with each match as a button → clicking a match shows details |
| `/fetch` | "Select a match:" | Buttons for current matches → "Select odds types:" multi-select buttons for odds types → "Fetching..." → results |
| `/odds` | "Select a match:" | Buttons for matches in DB → "Select odds type:" buttons for available types → show latest odds |
| `/rules` | List rules with enable/disable/delete buttons inline | Each rule row has [Enable]/[Disable]/[Delete] buttons |
| `/addrule` | **Multi-step wizard**: Step 1: "Select tournaments:" (buttons) → Step 2: "Select odds types:" (buttons) → Step 3: "Select schedule mode:" [Event]/[Continuous] → Step 4a (event): "Select trigger:" [before_kickoff]/[at_kickoff]/[at_halftime] → Step 4b: "Minutes before?" [15]/[30]/[60] → Step 5: "Rule name?" (text input) → Confirm | Full button-guided flow |
| `/enablerule` | "Select rule to enable:" | Buttons for disabled rules |
| `/disablerule` | "Select rule to disable:" | Buttons for enabled rules |
| `/deleterule` | "Select rule to delete:" | Buttons for all rules + [Cancel] |

### Callback Data Encoding

Since `data` is limited to 64 bytes, use short prefixes:
```
"m:EPL"              → matches tournament filter
"m:FB4233"           → match detail / selection
"f:FB4233"           → fetch: match selected
"f:FB4233:HAD,HHA"   → fetch: match + odds types confirmed
"o:FB4233"           → odds: match selected
"o:FB4233:CHL"       → odds: match + type selected
"r:enable:RuleName"   → rule enable
"r:disable:RuleName"  → rule disable
"r:del:RuleName"      → rule delete
"r:del:confirm:Name"  → rule delete confirmed
"ar:t:EPL"           → addrule wizard: tournament selected
"ar:o:HAD"           → addrule wizard: odds type toggled
"ar:s:event"         → addrule wizard: schedule mode
"ar:tr:before_ko"    → addrule wizard: trigger event
"ar:min:30"          → addrule wizard: minutes
"ar:confirm"         → addrule wizard: finalize
"cancel"             → cancel any operation
```

### Wizard State Management for `/addrule`

The `/addrule` wizard is multi-step and needs state tracking. Options:
- **In-memory dict**: `_wizard_state: dict[int, dict]` keyed by user ID. Stores the accumulated selections (tournaments, odds types, schedule, etc.) as the user clicks through steps.
- State is cleared on completion, cancellation, or timeout (5 minutes).
- Only one wizard per user at a time.

```python
class AddRuleWizard:
    """Tracks state for a multi-step /addrule conversation."""
    def __init__(self):
        self.tournaments: list[str] = []
        self.odds_types: list[str] = []
        self.schedule_mode: str = ""  # "event" or "continuous"
        self.trigger_event: str = ""  # "before_kickoff", etc.
        self.trigger_minutes: int = 0
        self.interval_seconds: int = 0
        self.start_event: str = ""
        self.end_event: str = ""
        self.step: str = "tournaments"  # current step
        self.created_at: datetime = datetime.now()
```

### New Config Fields

```python
# In config.py
TG_COMMANDS_ENABLED: bool = False      # Master toggle for command listener
TG_COMMAND_ALLOWED_USERS: str = ""     # Comma-separated Telegram user IDs (empty = allow all in group)
```

### New File: `src/hkjc_scrapper/tg_commands.py`

Separate module to keep `tg_msg_client.py` manageable.

```python
class TGCommandHandler:
    def __init__(self, tg_client: TelegramClient, db: MongoDBClient,
                 api_client: HKJCGraphQLClient, settings: Settings):
        self.client = tg_client
        self.db = db
        self.api = api_client
        self.settings = settings
        self._allowed_users: set[int] = self._parse_allowed_users()
        self._addrule_wizards: dict[int, AddRuleWizard] = {}  # user_id -> wizard state

    def register_handlers(self):
        """Register all command + callback handlers with the Telethon client."""
        # Text commands
        self.client.on(events.NewMessage(pattern='/help'))(self._cmd_help)
        self.client.on(events.NewMessage(pattern='/status'))(self._cmd_status)
        self.client.on(events.NewMessage(pattern='/matches'))(self._cmd_matches)
        self.client.on(events.NewMessage(pattern='/fetch'))(self._cmd_fetch)
        self.client.on(events.NewMessage(pattern='/odds'))(self._cmd_odds)
        self.client.on(events.NewMessage(pattern='/rules'))(self._cmd_rules)
        self.client.on(events.NewMessage(pattern='/addrule'))(self._cmd_addrule)
        self.client.on(events.NewMessage(pattern='/enablerule'))(self._cmd_enablerule)
        self.client.on(events.NewMessage(pattern='/disablerule'))(self._cmd_disablerule)
        self.client.on(events.NewMessage(pattern='/deleterule'))(self._cmd_deleterule)

        # Callback query handlers (button clicks)
        self.client.on(events.CallbackQuery(pattern=b"m:"))(self._cb_matches)
        self.client.on(events.CallbackQuery(pattern=b"f:"))(self._cb_fetch)
        self.client.on(events.CallbackQuery(pattern=b"o:"))(self._cb_odds)
        self.client.on(events.CallbackQuery(pattern=b"r:"))(self._cb_rules)
        self.client.on(events.CallbackQuery(pattern=b"ar:"))(self._cb_addrule)
        self.client.on(events.CallbackQuery(pattern=b"cancel"))(self._cb_cancel)

    async def _check_auth(self, event) -> bool:
        """Check if sender is authorized."""
        if not self._allowed_users:
            return True
        sender_id = event.sender_id
        if sender_id in self._allowed_users:
            return True
        await event.reply("Unauthorized.")
        return False
```

**Critical design decisions**:
- **Sync calls in executor**: pymongo and requests are synchronous. All DB/API calls wrapped in `loop.run_in_executor(None, ...)` to avoid blocking the Telethon event loop.
- **Long-running commands** (`/fetch`): Reply "Fetching..." first, then call API, then edit message with results.
- **Message length**: Telegram 4096 char limit. Paginate with "Next page" buttons if needed.
- **Button rows**: Max ~8 buttons visible comfortably. For long lists (matches, tournaments), paginate with [◀ Prev] [Next ▶] buttons.
- **Reuse existing logic**: `parse_observation()` from cli.py, `parse_matches_response()` from parser.py, db CRUD methods.

### Changes to `src/hkjc_scrapper/tg_msg_client.py`

1. **Refactor `run_loop()`**: Replace sleep-poll with `run_until_disconnected()`:
   ```python
   def run_loop():
       self._loop = asyncio.new_event_loop()
       asyncio.set_event_loop(self._loop)
       try:
           self._loop.run_until_complete(self._async_init())
           self._ready.set()
           # run_until_disconnected keeps loop alive AND processes incoming events
           self._loop.run_until_complete(self._client.run_until_disconnected())
       except Exception:
           logger.exception("[TG] Event loop thread crashed")
           self._ready.set()
   ```

2. **Two-phase startup**:
   - `__init__` stores config but does NOT start the thread
   - `start()` method starts the event loop thread. Called by `main.py` after all deps are wired.
   - `enable_commands(db, api_client)` must be called BEFORE `start()` if commands are enabled. It creates the `TGCommandHandler` and stores it. During `_async_init()`, if handler exists, `handler.register_handlers()` is called before `run_until_disconnected()`.

   **New init flow in main.py**:
   ```python
   tg = TGMessageClient(settings)          # stores config, no thread yet
   db = MongoDBClient(...)
   client = HKJCGraphQLClient(...)
   if settings.TG_COMMANDS_ENABLED:
       tg.enable_commands(db, client)       # sets handler, no thread yet
   tg.start()                              # starts thread, connects, registers handlers, runs
   scheduler = MatchScheduler(client, db, settings, tg=tg)
   ```

3. **Update `close()`**: Call `client.disconnect()` to break `run_until_disconnected()`, instead of setting `_shutdown` flag. Keep `_shutdown` as a secondary signal for backward compat.

### Changes to `src/hkjc_scrapper/main.py`

Update initialization order as shown above. The key change is separating TG client construction from thread start.

### BotFather Setup

Register commands with `/setcommands`:
```
help - Show available commands
status - Bot status and uptime
matches - Browse current HKJC matches
fetch - Fetch odds for a match
odds - View odds history
rules - Manage watch rules
addrule - Create a new watch rule
enablerule - Enable a watch rule
disablerule - Disable a watch rule
deleterule - Delete a watch rule
```

### Tests

**`tests/test_tg_commands.py`** (NEW):
- Test each command handler with mocked db/api/TelegramClient
- Test callback query handlers with mocked event.data
- Test authorization (allowed user, rejected user, empty allow list)
- Test AddRuleWizard state management (step transitions, timeout cleanup)
- Test button generation for match lists, rule lists
- Test response formatting and 4096-char truncation
- Test pagination for long match lists

**`tests/test_tg_msg_client.py`** (UPDATE):
- Test two-phase init (`enable_commands` before `start`)
- Test `start()` without commands (backward compat — should behave like before)
- Test shutdown via `disconnect()`

---

## Summary of All Config Changes

| Field | Type | Default | Enhancement |
|-------|------|---------|-------------|
| `TG_FETCH_INCLUDE_ODDS` | `bool` | `False` | #2 |
| `TG_DISCOVERY_INCLUDE_RULES` | `bool` | `False` | #3 |
| `TG_COMMANDS_ENABLED` | `bool` | `False` | #4 |
| `TG_COMMAND_ALLOWED_USERS` | `str` | `""` | #4 |

## Summary of All File Changes

| File | Enhancements | Change Type |
|------|-------------|-------------|
| `src/hkjc_scrapper/config.py` | 2, 3, 4 | Add 4 config fields |
| `src/hkjc_scrapper/tg_msg_client.py` | 2, 3, 4, 5 | Add notify_error; extend notify_fetch/notify_discovery; refactor to two-phase init (constructor + start()); add enable_commands(); replace sleep-poll with run_until_disconnected() |
| `src/hkjc_scrapper/tg_commands.py` | 4 | **NEW** — TGCommandHandler class with NewMessage + CallbackQuery handlers, AddRuleWizard state machine, inline button builders, pagination |
| `src/hkjc_scrapper/scheduler.py` | 2, 3, 5 | Add error notifications in catch blocks; pass odds/rule details to TG |
| `src/hkjc_scrapper/cli.py` | 1, 2 | Add --time-series + --limit flags and `_print_odds_time_series()` formatter; pass odds details to TG on fetch |
| `src/hkjc_scrapper/main.py` | 4 | Restructure init order: create TG → create DB/client → enable_commands → tg.start() → create scheduler |
| `tests/test_tg_msg_client.py` | 2, 3, 4, 5 | Tests for notify_error, extended notify_fetch/notify_discovery, two-phase init, shutdown via disconnect |
| `tests/test_tg_commands.py` | 4 | **NEW** — Tests for all command handlers, callback handlers, wizard state, auth, button generation, pagination |
| `tests/test_cli.py` | 1 | Tests for --time-series formatting with change indicators, --limit flag |
| `tests/test_scheduler.py` | 5 | Tests for error notification calls in discovery/fetch |

## Verification

After each enhancement, run: `uv run pytest tests/ -v -m "not integration and not mongodb"`

| Enhancement | Manual Verification |
|-------------|-------------------|
| #5 Error notifications | Simulate API failure (e.g., wrong endpoint), verify TG error message received |
| #2 Odds in fetch msg | Set `TG_FETCH_INCLUDE_ODDS=true`, run `--once`, verify all-lines odds detail in TG |
| #3 Rules in discovery msg | Set `TG_DISCOVERY_INCLUDE_RULES=true`, run service, verify per-rule breakdown |
| #1 Time-series CLI | `uv run python -m hkjc_scrapper.cli get-odds --front-end-id FB4233 --odds CHL --ts` |
| #1 Time-series --limit | `uv run python -m hkjc_scrapper.cli get-odds --front-end-id FB4233 --odds CHL --ts --limit 10` |
| #4 TG bot commands | Set `TG_COMMANDS_ENABLED=true`, send `/help` → verify response, `/matches` → verify buttons, `/deleterule` → verify rule buttons appear, `/addrule` → verify wizard flow step by step |
