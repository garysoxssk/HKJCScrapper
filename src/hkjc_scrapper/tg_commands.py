"""Telegram command handler for interactive bot commands.

Implements /command handlers and inline button callbacks for remote control
of the HKJC Scrapper via Telegram. Uses Telethon's event system.

Commands:
    /help           - Show available commands
    /status         - Bot status (uptime, rules)
    /jobs           - View scheduled fetch jobs from DB
    /matches        - Browse current HKJC matches with tournament buttons
    /fetch          - Fetch odds for a match (guided with buttons)
    /odds           - View odds history (guided with buttons)
    /rules          - Manage watch rules with inline enable/disable/delete buttons
    /addrule        - Multi-step wizard to create a new rule
    /enablerule     - Show disabled rules as buttons to enable
    /disablerule    - Show enabled rules as buttons to disable
    /deleterule     - Show all rules as buttons to delete
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from telethon import Button, events

from hkjc_scrapper.config import Settings

logger = logging.getLogger(__name__)

# Telegram message length limit (leave some headroom)
TG_MAX_LENGTH = 4000


def _job_sort_key(job: dict) -> datetime:
    """Sort key: event by trigger_time, continuous by start_time."""
    t = job.get("trigger_time") or job.get("start_time")
    if t is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _truncate(text: str, limit: int = TG_MAX_LENGTH) -> str:
    """Truncate text to limit, adding '... (truncated)' if needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 15] + "... (truncated)"


def _format_rule_detail(rule: dict) -> str:
    """Format a rule's details (filters, observations) for display."""
    parts: list[str] = []
    mf = rule.get("match_filter", {})
    teams = mf.get("teams", [])
    tournaments = mf.get("tournaments", [])
    match_ids = mf.get("match_ids", [])
    if teams:
        parts.append(f"  Teams: {', '.join(teams)}")
    if tournaments:
        parts.append(f"  Tournaments: {', '.join(tournaments)}")
    if match_ids:
        parts.append(f"  Match IDs: {', '.join(match_ids)}")
    if not teams and not tournaments and not match_ids:
        parts.append("  Filter: all matches")

    for obs in rule.get("observations", []):
        odds = ", ".join(obs.get("odds_types", []))
        sched = obs.get("schedule", {})
        mode = sched.get("mode", "?")
        if mode == "event":
            triggers = sched.get("triggers", [])
            trigger_strs = []
            for t in triggers:
                ev = t.get("event", "?")
                mins = t.get("minutes")
                trigger_strs.append(f"{ev} ({mins}min)" if mins else ev)
            parts.append(f"  Odds: {odds} | {mode} — {', '.join(trigger_strs)}")
        elif mode == "continuous":
            interval = sched.get("interval_seconds", "?")
            start = sched.get("start_event", "?")
            end = sched.get("end_event", "?")
            parts.append(f"  Odds: {odds} | every {interval}s ({start} \u2192 {end})")
        else:
            parts.append(f"  Odds: {odds}")
    return "\n".join(parts)


def _format_relative_to_kickoff(fetched_at: datetime, kickoff_str: str) -> str | None:
    """Format time relative to kickoff. Returns None if kickoff can't be parsed."""
    try:
        kickoff_dt = datetime.fromisoformat(kickoff_str)
        # Ensure both are tz-aware or both naive for comparison
        if kickoff_dt.tzinfo is None and fetched_at.tzinfo is not None:
            kickoff_dt = kickoff_dt.replace(tzinfo=timezone.utc)
        elif kickoff_dt.tzinfo is not None and fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        delta = fetched_at - kickoff_dt
        total_minutes = int(delta.total_seconds() / 60)
        abs_minutes = abs(total_minutes)
        if abs_minutes == 0:
            return "at kickoff"
        if abs_minutes >= 120:
            hours = abs_minutes // 60
            label = f"{hours} hours"
        else:
            label = f"{abs_minutes} min"
        if total_minutes < 0:
            return f"{label} before kickoff"
        return f"{label} after kickoff"
    except (ValueError, TypeError):
        return None


@dataclass
class AddRuleWizard:
    """Tracks multi-step /addrule conversation state per user."""

    tournaments: list = field(default_factory=list)
    odds_types: list = field(default_factory=list)
    schedule_mode: str = ""          # "event" or "continuous"
    trigger_event: str = ""          # "before_kickoff", "at_kickoff", "at_halftime"
    trigger_minutes: int = 0
    interval_seconds: int = 0
    start_event: str = ""
    end_event: str = ""
    step: str = "tournaments"        # Current wizard step
    created_at: datetime = field(default_factory=datetime.now)

    def is_timed_out(self, timeout_seconds: int = 300) -> bool:
        """Return True if the wizard has been idle longer than timeout."""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > timeout_seconds


# Available options for wizard steps
_TOURNAMENT_OPTIONS = ["EPL", "LLG", "UCL", "SFL", "ITL", "GLL", "CL1", "WC"]
_ODDS_TYPE_OPTIONS = ["HAD", "HHA", "HDC", "HIL", "CHL", "CRS", "TTG", "FHA", "FHL", "CHD"]
_TRIGGER_OPTIONS = ["before_kickoff", "at_kickoff", "at_halftime", "after_kickoff"]
_MINUTES_OPTIONS = [15, 30, 60]
_INTERVAL_OPTIONS = [60, 120, 300, 600]
_EVENT_BOUNDARY_OPTIONS = ["kickoff", "halftime", "fulltime"]


class TGCommandHandler:
    """Handles incoming Telegram commands and button callbacks."""

    def __init__(self, tg_client, db, api_client, settings: Settings):
        """
        Args:
            tg_client: Telethon TelegramClient instance
            db: MongoDBClient instance
            api_client: HKJCGraphQLClient instance
            settings: Application settings
        """
        self.client = tg_client
        self.db = db
        self.api = api_client
        self.settings = settings
        self._allowed_users: set[int] = self._parse_allowed_users()
        self._addrule_wizards: dict[int, AddRuleWizard] = {}
        self._started_at = datetime.now()

    def _parse_allowed_users(self) -> set[int]:
        """Parse TG_COMMAND_ALLOWED_USERS into a set of user IDs."""
        raw = getattr(self.settings, "TG_COMMAND_ALLOWED_USERS", "").strip()
        if not raw:
            return set()
        result = set()
        for uid in raw.split(","):
            uid = uid.strip()
            if uid:
                try:
                    result.add(int(uid))
                except ValueError:
                    logger.warning("[TGCmd] Invalid user ID in TG_COMMAND_ALLOWED_USERS: %s", uid)
        return result

    def register_handlers(self) -> None:
        """Register all command and callback handlers with the Telethon client."""
        # Text commands
        self.client.on(events.NewMessage(pattern=r"^/help"))(self._cmd_help)
        self.client.on(events.NewMessage(pattern=r"^/status"))(self._cmd_status)
        self.client.on(events.NewMessage(pattern=r"^/matches"))(self._cmd_matches)
        self.client.on(events.NewMessage(pattern=r"^/fetch"))(self._cmd_fetch)
        self.client.on(events.NewMessage(pattern=r"^/odds"))(self._cmd_odds)
        self.client.on(events.NewMessage(pattern=r"^/rules"))(self._cmd_rules)
        self.client.on(events.NewMessage(pattern=r"^/addrule"))(self._cmd_addrule)
        self.client.on(events.NewMessage(pattern=r"^/jobs"))(self._cmd_jobs)
        self.client.on(events.NewMessage(pattern=r"^/enablerule"))(self._cmd_enablerule)
        self.client.on(events.NewMessage(pattern=r"^/disablerule"))(self._cmd_disablerule)
        self.client.on(events.NewMessage(pattern=r"^/deleterule"))(self._cmd_deleterule)

        # General message handler for wizard text input (rule name step)
        self.client.on(events.NewMessage())(self._on_any_message)

        # Callback query handlers (button clicks)
        self.client.on(events.CallbackQuery(pattern=b"^m:"))(self._cb_matches)
        self.client.on(events.CallbackQuery(pattern=b"^f:"))(self._cb_fetch)
        self.client.on(events.CallbackQuery(pattern=b"^o:"))(self._cb_odds)
        self.client.on(events.CallbackQuery(pattern=b"^r:"))(self._cb_rules)
        self.client.on(events.CallbackQuery(pattern=b"^ar:"))(self._cb_addrule)
        self.client.on(events.CallbackQuery(pattern=b"^cancel$"))(self._cb_cancel)

    # ========================================================================
    # Auth helper
    # ========================================================================

    async def _check_auth(self, event) -> bool:
        """Return True if sender is authorized to use commands."""
        if not self._allowed_users:
            return True
        sender_id = event.sender_id
        if sender_id in self._allowed_users:
            return True
        await event.reply("Unauthorized.")
        return False

    # ========================================================================
    # Command handlers
    # ========================================================================

    async def _cmd_help(self, event) -> None:
        """Handle /help command."""
        if not await self._check_auth(event):
            return
        text = (
            "<b>HKJC Scrapper Commands</b>\n\n"
            "/help — Show this help message\n"
            "/status — Bot status (uptime, rules)\n"
            "/jobs — View scheduled fetch jobs\n"
            "/matches — Browse current HKJC matches\n"
            "/fetch — Fetch and save odds for a match\n"
            "/odds — View stored odds history\n"
            "/rules — Manage watch rules\n"
            "/addrule — Create a new watch rule (guided wizard)\n"
            "/enablerule — Enable a disabled rule\n"
            "/disablerule — Disable an active rule\n"
            "/deleterule — Delete a rule permanently"
        )
        await event.reply(text, parse_mode="html")

    async def _cmd_status(self, event) -> None:
        """Handle /status command."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        rules = await loop.run_in_executor(None, self.db.get_active_watch_rules)
        uptime_secs = int((datetime.now() - self._started_at).total_seconds())
        uptime_str = f"{uptime_secs // 3600}h {(uptime_secs % 3600) // 60}m"
        text = (
            "<b>Bot Status</b>\n"
            f"Active rules: {len(rules)}\n"
            f"Uptime: {uptime_str}"
        )
        await event.reply(text, parse_mode="html")

    async def _cmd_jobs(self, event) -> None:
        """Handle /jobs command — show persisted scheduled fetch jobs."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        jobs = await loop.run_in_executor(None, self.db.get_all_scheduled_jobs)
        if not jobs:
            await event.reply("No scheduled jobs.")
            return
        jobs.sort(key=_job_sort_key)

        tz = self.settings.tz
        lines = [f"<b>Scheduled Jobs ({len(jobs)})</b>", ""]
        for i, j in enumerate(jobs, 1):
            feid = j.get("front_end_id", "?")
            odds = ", ".join(j.get("odds_types", []))
            jtype = j.get("job_type", "?")

            if jtype == "event":
                tt = j.get("trigger_time")
                if tt:
                    if tt.tzinfo is None:
                        tt = tt.replace(tzinfo=timezone.utc)
                    window = tt.astimezone(tz).strftime("%Y-%m-%d %H:%M HKT")
                else:
                    window = "?"
            elif jtype == "continuous":
                interval = j.get("interval_seconds", "?")
                st = j.get("start_time")
                et = j.get("end_time")
                if st and et:
                    if st.tzinfo is None:
                        st = st.replace(tzinfo=timezone.utc)
                    if et.tzinfo is None:
                        et = et.replace(tzinfo=timezone.utc)
                    st_hk = st.astimezone(tz)
                    et_hk = et.astimezone(tz)
                    window = (
                        f"every {interval}s, "
                        f"{st_hk.strftime('%H:%M')}–{et_hk.strftime('%H:%M')} "
                        f"{st_hk.strftime('%b %d')} HKT"
                    )
                else:
                    window = f"every {interval}s"
            else:
                window = "?"

            lines.append(f"{i}. <b>{feid}</b> — {odds} ({jtype})")
            lines.append(f"   {window}")

        text = "\n".join(lines)
        await event.reply(_truncate(text), parse_mode="html")

    async def _cmd_matches(self, event) -> None:
        """Handle /matches command — show tournament selection buttons."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, self.api.send_basic_match_list_request)
        except Exception as e:
            await event.reply(f"Error fetching matches: {e}")
            return

        from hkjc_scrapper.parser import parse_matches_response
        matches = parse_matches_response(raw)
        if not matches:
            await event.reply("No matches found.")
            return

        # Group by tournament
        tournaments: dict[str, int] = {}
        for m in matches:
            code = m.tournament.code
            tournaments[code] = tournaments.get(code, 0) + 1

        buttons = [
            [Button.inline(f"{code} ({count})", data=f"m:{code}".encode())]
            for code, count in sorted(tournaments.items())
        ]
        buttons.append([Button.inline("Cancel", data=b"cancel")])
        await event.reply("Select a tournament:", buttons=buttons)

    async def _cmd_fetch(self, event) -> None:
        """Handle /fetch command — show match selection buttons."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, self.api.send_basic_match_list_request)
        except Exception as e:
            await event.reply(f"Error fetching matches: {e}")
            return

        from hkjc_scrapper.parser import parse_matches_response
        matches = parse_matches_response(raw)
        if not matches:
            await event.reply("No matches found.")
            return

        buttons = []
        for m in matches[:15]:  # limit to avoid too many buttons
            label = f"{m.homeTeam.name_en[:10]} vs {m.awayTeam.name_en[:10]}"
            data = f"f:{m.frontEndId}".encode()
            if len(data) <= 64:
                buttons.append([Button.inline(label, data=data)])
        buttons.append([Button.inline("Cancel", data=b"cancel")])
        await event.reply("Select a match to fetch:", buttons=buttons)

    async def _cmd_odds(self, event) -> None:
        """Handle /odds command — show stored matches as buttons."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        matches = await loop.run_in_executor(None, lambda: list(
            self.db.matches_current.find({}, {"_id": 1, "frontEndId": 1,
                                             "homeTeam": 1, "awayTeam": 1}).limit(15)
        ))
        if not matches:
            await event.reply("No matches in database.")
            return

        buttons = []
        for m in matches:
            feid = m.get("frontEndId", "?")
            home = m.get("homeTeam", {}).get("name_en", "?")[:10]
            away = m.get("awayTeam", {}).get("name_en", "?")[:10]
            label = f"{home} vs {away}"
            data = f"o:{feid}".encode()
            if len(data) <= 64:
                buttons.append([Button.inline(label, data=data)])
        buttons.append([Button.inline("Cancel", data=b"cancel")])
        await event.reply("Select a match:", buttons=buttons)

    async def _cmd_rules(self, event) -> None:
        """Handle /rules command — list rules with inline buttons."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        rules = await loop.run_in_executor(None, self.db.get_all_watch_rules)
        if not rules:
            await event.reply("No watch rules found.")
            return

        lines = ["<b>Watch Rules</b>\n"]
        buttons = []
        for idx, rule in enumerate(rules, 1):
            name = rule["name"]
            status = "✅" if rule.get("enabled", True) else "❌"
            lines.append(f"<b>#{idx}</b> {status} {name}")
            lines.append(_format_rule_detail(rule))
            lines.append("")  # blank line between rules
            action = "disable" if rule.get("enabled", True) else "enable"
            action_label = "Disable" if rule.get("enabled", True) else "Enable"
            row = [
                Button.inline(f"{action_label} #{idx}",
                               data=f"r:{action}:{name}".encode()[:64]),
                Button.inline(f"Delete #{idx}", data=f"r:del:{name}".encode()[:64]),
            ]
            buttons.append(row)
        buttons.append([Button.inline("Close", data=b"cancel")])

        text = _truncate("\n".join(lines))
        await event.reply(text, buttons=buttons, parse_mode="html")

    async def _cmd_addrule(self, event) -> None:
        """Handle /addrule command — start rule creation wizard."""
        if not await self._check_auth(event):
            return
        user_id = event.sender_id
        # Start a new wizard (overwrite any existing)
        self._addrule_wizards[user_id] = AddRuleWizard()
        await self._send_wizard_step(event, user_id)

    async def _cmd_enablerule(self, event) -> None:
        """Handle /enablerule command — show disabled rules as buttons."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        all_rules = await loop.run_in_executor(None, self.db.get_all_watch_rules)
        disabled = [r for r in all_rules if not r.get("enabled", True)]
        if not disabled:
            await event.reply("No disabled rules found.")
            return
        buttons = [
            [Button.inline(r["name"], data=f"r:enable:{r['name']}".encode()[:64])]
            for r in disabled
        ]
        buttons.append([Button.inline("Cancel", data=b"cancel")])
        await event.reply("Select rule to enable:", buttons=buttons)

    async def _cmd_disablerule(self, event) -> None:
        """Handle /disablerule command — show enabled rules as buttons."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        rules = await loop.run_in_executor(None, self.db.get_active_watch_rules)
        if not rules:
            await event.reply("No active rules found.")
            return
        buttons = [
            [Button.inline(r.name, data=f"r:disable:{r.name}".encode()[:64])]
            for r in rules
        ]
        buttons.append([Button.inline("Cancel", data=b"cancel")])
        await event.reply("Select rule to disable:", buttons=buttons)

    async def _cmd_deleterule(self, event) -> None:
        """Handle /deleterule command — show all rules as buttons."""
        if not await self._check_auth(event):
            return
        loop = asyncio.get_event_loop()
        all_rules = await loop.run_in_executor(None, self.db.get_all_watch_rules)
        if not all_rules:
            await event.reply("No rules found.")
            return
        buttons = [
            [Button.inline(r["name"], data=f"r:del:{r['name']}".encode()[:64])]
            for r in all_rules
        ]
        buttons.append([Button.inline("Cancel", data=b"cancel")])
        await event.reply("Select rule to delete:", buttons=buttons)

    # ========================================================================
    # Callback query handlers (button clicks)
    # ========================================================================

    async def _cb_matches(self, event) -> None:
        """Handle m: callbacks — tournament selection or match detail."""
        if not await self._check_auth(event):
            return
        data = event.data.decode()
        parts = data.split(":", 1)
        value = parts[1] if len(parts) > 1 else ""

        await event.answer()

        if value.startswith("FB"):
            # Match detail
            loop = asyncio.get_event_loop()
            try:
                raw = await loop.run_in_executor(None, self.api.send_basic_match_list_request)
                from hkjc_scrapper.parser import parse_matches_response
                matches = parse_matches_response(raw)
                match = next((m for m in matches if m.frontEndId == value), None)
                if match:
                    text = (
                        f"<b>{match.homeTeam.name_en}</b> vs <b>{match.awayTeam.name_en}</b>\n"
                        f"ID: {match.frontEndId}\n"
                        f"Tournament: {match.tournament.name_en} ({match.tournament.code})\n"
                        f"Kickoff: {match.kickOffTime[:16].replace('T', ' ')}\n"
                        f"Status: {match.status}"
                    )
                    await event.edit(text, parse_mode="html")
                else:
                    await event.edit(f"Match {value} not found.")
            except Exception as e:
                await event.edit(f"Error: {e}")
        else:
            # Tournament filter — show matches in that tournament
            loop = asyncio.get_event_loop()
            try:
                raw = await loop.run_in_executor(None, self.api.send_basic_match_list_request)
                from hkjc_scrapper.parser import parse_matches_response
                matches = parse_matches_response(raw)
                tourn_matches = [m for m in matches if m.tournament.code == value]
                if not tourn_matches:
                    await event.edit(f"No matches found for {value}.")
                    return
                buttons = []
                for m in tourn_matches[:10]:
                    label = f"{m.homeTeam.name_en[:12]} vs {m.awayTeam.name_en[:12]}"
                    data = f"m:{m.frontEndId}".encode()
                    if len(data) <= 64:
                        buttons.append([Button.inline(label, data=data)])
                buttons.append([Button.inline("Back", data=b"cancel")])
                await event.edit(f"Matches in {value}:", buttons=buttons)
            except Exception as e:
                await event.edit(f"Error: {e}")

    async def _cb_fetch(self, event) -> None:
        """Handle f: callbacks — match selection then odds type selection then fetch."""
        if not await self._check_auth(event):
            return
        data = event.data.decode()
        await event.answer()

        parts = data.split(":", 2)
        if len(parts) == 2:
            # f:FB1234 — show odds type selection
            front_end_id = parts[1]
            buttons = []
            row = []
            for ot in ["HAD", "HHA", "CHL", "HDC", "HIL", "FHA"]:
                row.append(Button.inline(ot, data=f"f:{front_end_id}:{ot}".encode()[:64]))
                if len(row) == 3:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await event.edit("Select odds type to fetch:", buttons=buttons)
        elif len(parts) == 3:
            # f:FB1234:HAD — execute fetch
            front_end_id = parts[1]
            odds_type = parts[2]
            msg = await event.edit(f"Fetching {odds_type} for {front_end_id}...")
            loop = asyncio.get_event_loop()
            try:
                raw = await loop.run_in_executor(
                    None,
                    lambda: self.api.fetch_matches_for_odds(
                        odds_types=[odds_type], with_preflight=True
                    )
                )
                from hkjc_scrapper.parser import parse_matches_response
                matches = parse_matches_response(raw)
                target = next((m for m in matches if m.frontEndId == front_end_id), None)
                if target is None:
                    await event.edit(f"Match {front_end_id} not found in API response.")
                    return
                result = await loop.run_in_executor(None, lambda: self.db.save_matches([target]))
                lines = [
                    f"<b>Fetched: {front_end_id}</b>",
                    f"{target.homeTeam.name_en} vs {target.awayTeam.name_en}",
                    f"Odds type: {odds_type}",
                    f"Snapshots saved: {result['odds_snapshots']}",
                    "",
                ]
                for pool in target.foPools:
                    if pool.oddsType == odds_type:
                        for ln in pool.lines:
                            cond = ln.condition
                            main_flag = " (main)" if ln.main else ""
                            comb_str = " | ".join(
                                f"{c.str}={c.currentOdds}" for c in ln.combinations
                            )
                            cond_str = f"[{cond}] " if cond else ""
                            lines.append(f"  {cond_str}{comb_str}{main_flag}")
                text = "\n".join(lines)
                await event.edit(_truncate(text), parse_mode="html")
            except Exception as e:
                await event.edit(f"Error fetching {front_end_id}: {e}")

    async def _cb_odds(self, event) -> None:
        """Handle o: callbacks — match then odds type selection then show latest odds."""
        if not await self._check_auth(event):
            return
        data = event.data.decode()
        await event.answer()

        parts = data.split(":", 2)
        if len(parts) == 2:
            # o:FB1234 — show available odds type buttons
            front_end_id = parts[1]
            loop = asyncio.get_event_loop()
            match_doc = await loop.run_in_executor(
                None, lambda: self.db.get_match_by_front_end_id(front_end_id)
            )
            if not match_doc:
                await event.edit(f"Match {front_end_id} not found in DB.")
                return
            match_id = match_doc["_id"]
            available = await loop.run_in_executor(
                None, lambda: self.db.get_odds_distinct_types(match_id)
            )
            if not available:
                await event.edit(f"No odds history for {front_end_id}.")
                return
            buttons = [
                [Button.inline(ot, data=f"o:{front_end_id}:{ot}".encode()[:64])]
                for ot in sorted(available)
            ]
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await event.edit(f"Select odds type for {front_end_id}:", buttons=buttons)
        elif len(parts) == 3:
            # o:FB1234:CHL — show latest odds
            front_end_id = parts[1]
            odds_type = parts[2]
            loop = asyncio.get_event_loop()
            match_doc = await loop.run_in_executor(
                None, lambda: self.db.get_match_by_front_end_id(front_end_id)
            )
            if not match_doc:
                await event.edit(f"Match {front_end_id} not found.")
                return
            match_id = match_doc["_id"]
            snapshots = await loop.run_in_executor(
                None, lambda: self.db.get_latest_odds(match_id, odds_type=odds_type)
            )
            if not snapshots:
                await event.edit(f"No {odds_type} odds for {front_end_id}.")
                return
            snap = snapshots[0]
            # Format fetch time and relative time to kickoff
            header_lines = [f"<b>{odds_type} odds — {front_end_id}</b>"]
            fetched_at = snap.get("fetchedAt")
            if fetched_at and isinstance(fetched_at, datetime):
                header_lines.append(
                    f"\U0001f550 Fetched: {fetched_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
                )
                kickoff_str = match_doc.get("kickOffTime")
                if kickoff_str:
                    relative = _format_relative_to_kickoff(fetched_at, kickoff_str)
                    if relative:
                        header_lines.append(f"\u23f1 {relative}")
            header_lines.append("")  # blank line before odds

            lines = []
            for line in snap.get("lines", []):
                cond = line.get("condition")
                main_flag = " (main)" if line.get("main") else ""
                comb_str = " | ".join(
                    f"{c.get('str', '?')}={c.get('currentOdds', '?')}"
                    for c in line.get("combinations", [])
                )
                cond_str = f"[{cond}] " if cond else ""
                lines.append(f"  {cond_str}{comb_str}{main_flag}")
            text = "\n".join(header_lines) + "\n".join(lines)
            await event.edit(_truncate(text), parse_mode="html")

    async def _cb_rules(self, event) -> None:
        """Handle r: callbacks — enable/disable/delete rule actions."""
        if not await self._check_auth(event):
            return
        data = event.data.decode()
        await event.answer()

        parts = data.split(":", 3)
        # parts[0] = "r"
        action = parts[1] if len(parts) > 1 else ""

        if action == "enable" and len(parts) >= 3:
            rule_name = parts[2]
            loop = asyncio.get_event_loop()
            ok = await loop.run_in_executor(None, lambda: self.db.enable_watch_rule(rule_name))
            if ok:
                await event.edit(f"Rule <b>{rule_name}</b> enabled.", parse_mode="html")
            else:
                await event.edit(f"Rule '{rule_name}' not found.")

        elif action == "disable" and len(parts) >= 3:
            rule_name = parts[2]
            loop = asyncio.get_event_loop()
            ok = await loop.run_in_executor(None, lambda: self.db.disable_watch_rule(rule_name))
            if ok:
                await event.edit(f"Rule <b>{rule_name}</b> disabled.", parse_mode="html")
            else:
                await event.edit(f"Rule '{rule_name}' not found.")

        elif action == "del":
            if len(parts) >= 4 and parts[2] == "confirm":
                rule_name = parts[3]
                loop = asyncio.get_event_loop()
                ok = await loop.run_in_executor(None, lambda: self.db.delete_watch_rule(rule_name))
                if ok:
                    await event.edit(f"Rule <b>{rule_name}</b> deleted.", parse_mode="html")
                else:
                    await event.edit(f"Rule '{rule_name}' not found.")
            elif len(parts) >= 3:
                rule_name = parts[2]
                # Ask for confirmation
                buttons = [
                    [Button.inline("Confirm Delete", data=f"r:del:confirm:{rule_name}".encode()[:64])],
                    [Button.inline("Cancel", data=b"cancel")],
                ]
                await event.edit(
                    f"Delete rule <b>{rule_name}</b>?",
                    buttons=buttons,
                    parse_mode="html",
                )

    async def _cb_addrule(self, event) -> None:
        """Handle ar: callbacks — addrule wizard step transitions."""
        if not await self._check_auth(event):
            return
        user_id = event.sender_id
        await event.answer()

        wizard = self._addrule_wizards.get(user_id)
        if wizard is None:
            await event.edit("Wizard session expired. Use /addrule to start again.")
            return

        if wizard.is_timed_out():
            del self._addrule_wizards[user_id]
            await event.edit("Wizard timed out. Use /addrule to start again.")
            return

        data = event.data.decode()
        parts = data.split(":", 2)
        # parts[0] = "ar", parts[1] = action, parts[2] = value
        action = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""

        if action == "t":
            # Toggle tournament selection
            if value in wizard.tournaments:
                wizard.tournaments.remove(value)
            else:
                wizard.tournaments.append(value)
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "o":
            # Toggle odds type selection
            if value in wizard.odds_types:
                wizard.odds_types.remove(value)
            else:
                wizard.odds_types.append(value)
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "s":
            # Schedule mode selected
            wizard.schedule_mode = value
            wizard.step = "trigger_event" if value == "event" else "interval"
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "tr":
            # Trigger event selected
            wizard.trigger_event = value
            wizard.step = "trigger_minutes" if value == "before_kickoff" else "confirm_name"
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "min":
            wizard.trigger_minutes = int(value)
            wizard.step = "confirm_name"
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "int":
            wizard.interval_seconds = int(value)
            wizard.step = "start_event"
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "se":
            wizard.start_event = value
            wizard.step = "end_event"
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "ee":
            wizard.end_event = value
            wizard.step = "confirm_name"
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "next":
            # Advance from multi-select steps
            if wizard.step == "tournaments":
                if not wizard.tournaments:
                    await event.answer("Select at least one tournament.", alert=True)
                    return
                wizard.step = "odds_types"
            elif wizard.step == "odds_types":
                if not wizard.odds_types:
                    await event.answer("Select at least one odds type.", alert=True)
                    return
                wizard.step = "schedule_mode"
            await self._send_wizard_step(event, user_id, edit=True)

        elif action == "confirm":
            # Create the rule
            await self._finish_wizard(event, user_id)

    async def _cb_cancel(self, event) -> None:
        """Handle cancel button."""
        user_id = event.sender_id
        self._addrule_wizards.pop(user_id, None)
        await event.answer()
        await event.edit("Cancelled.")

    # ========================================================================
    # Wizard helpers
    # ========================================================================

    async def _send_wizard_step(self, event, user_id: int, edit: bool = False) -> None:
        """Send the appropriate message/buttons for the current wizard step."""
        wizard = self._addrule_wizards.get(user_id)
        if wizard is None:
            return

        step = wizard.step
        reply_fn = event.edit if edit else event.reply

        if step == "tournaments":
            buttons = []
            row = []
            for t in _TOURNAMENT_OPTIONS:
                tick = "✅" if t in wizard.tournaments else "⬜"
                row.append(Button.inline(f"{tick} {t}", data=f"ar:t:{t}".encode()))
                if len(row) == 4:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            selected = ", ".join(wizard.tournaments) if wizard.tournaments else "(none)"
            buttons.append([Button.inline("Next →", data=b"ar:next")])
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await reply_fn(
                f"<b>Step 1: Select tournaments</b>\nSelected: {selected}",
                buttons=buttons, parse_mode="html"
            )

        elif step == "odds_types":
            buttons = []
            row = []
            for ot in _ODDS_TYPE_OPTIONS:
                tick = "✅" if ot in wizard.odds_types else "⬜"
                row.append(Button.inline(f"{tick} {ot}", data=f"ar:o:{ot}".encode()))
                if len(row) == 3:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            selected = ", ".join(wizard.odds_types) if wizard.odds_types else "(none)"
            buttons.append([Button.inline("Next →", data=b"ar:next")])
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await reply_fn(
                f"<b>Step 2: Select odds types</b>\nSelected: {selected}",
                buttons=buttons, parse_mode="html"
            )

        elif step == "schedule_mode":
            buttons = [
                [Button.inline("Event-based", data=b"ar:s:event")],
                [Button.inline("Continuous polling", data=b"ar:s:continuous")],
                [Button.inline("Cancel", data=b"cancel")],
            ]
            await reply_fn("<b>Step 3: Schedule mode</b>", buttons=buttons, parse_mode="html")

        elif step == "trigger_event":
            buttons = [
                [Button.inline(t, data=f"ar:tr:{t}".encode())]
                for t in _TRIGGER_OPTIONS
            ]
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await reply_fn("<b>Step 4: Select trigger</b>", buttons=buttons, parse_mode="html")

        elif step == "trigger_minutes":
            buttons = [
                [Button.inline(f"{m} min", data=f"ar:min:{m}".encode())]
                for m in _MINUTES_OPTIONS
            ]
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await reply_fn(
                "<b>Step 4b: Minutes before kickoff?</b>",
                buttons=buttons, parse_mode="html"
            )

        elif step == "interval":
            buttons = [
                [Button.inline(f"{s}s", data=f"ar:int:{s}".encode())]
                for s in _INTERVAL_OPTIONS
            ]
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await reply_fn(
                "<b>Step 4: Polling interval (seconds)?</b>",
                buttons=buttons, parse_mode="html"
            )

        elif step == "start_event":
            buttons = [
                [Button.inline(e, data=f"ar:se:{e}".encode())]
                for e in _EVENT_BOUNDARY_OPTIONS
            ]
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await reply_fn("<b>Step 5: Start event?</b>", buttons=buttons, parse_mode="html")

        elif step == "end_event":
            buttons = [
                [Button.inline(e, data=f"ar:ee:{e}".encode())]
                for e in _EVENT_BOUNDARY_OPTIONS
            ]
            buttons.append([Button.inline("Cancel", data=b"cancel")])
            await reply_fn("<b>Step 6: End event?</b>", buttons=buttons, parse_mode="html")

        elif step == "confirm_name":
            # Prompt for rule name via text input
            wizard.step = "awaiting_name"
            await reply_fn(
                "Please type a name for this rule:\n(e.g., 'EPL HAD pre-kickoff')",
                parse_mode="html"
            )

    async def _on_any_message(self, event) -> None:
        """Catch-all handler for text messages — captures rule name in wizard."""
        user_id = event.sender_id
        wizard = self._addrule_wizards.get(user_id)
        if wizard is None or wizard.step != "awaiting_name":
            return
        # Skip command messages
        text = event.text or ""
        if text.startswith("/"):
            return
        if wizard.is_timed_out():
            del self._addrule_wizards[user_id]
            await event.reply("Wizard timed out. Use /addrule to start again.")
            return
        rule_name = text.strip()
        if not rule_name:
            await event.reply("Rule name cannot be empty. Please type a name:")
            return
        # Show confirmation
        wizard.step = "confirming"
        buttons = [
            [Button.inline("✅ Create Rule", data=b"ar:confirm")],
            [Button.inline("Cancel", data=b"cancel")],
        ]
        summary = self._wizard_summary(wizard, rule_name)
        wizard._pending_name = rule_name
        await event.reply(
            _truncate(f"<b>Confirm new rule: {rule_name}</b>\n\n{summary}"),
            buttons=buttons, parse_mode="html"
        )

    @staticmethod
    def _wizard_summary(wizard: AddRuleWizard, name: str) -> str:
        """Generate a text summary of wizard state."""
        lines = [
            f"Name: {name}",
            f"Tournaments: {', '.join(wizard.tournaments)}",
            f"Odds types: {', '.join(wizard.odds_types)}",
        ]
        if wizard.schedule_mode == "event":
            lines.append(f"Mode: event — {wizard.trigger_event}"
                         + (f" ({wizard.trigger_minutes}m)" if wizard.trigger_minutes else ""))
        elif wizard.schedule_mode == "continuous":
            lines.append(f"Mode: continuous every {wizard.interval_seconds}s "
                         f"({wizard.start_event} → {wizard.end_event})")
        return "\n".join(lines)

    async def _finish_wizard(self, event, user_id: int) -> None:
        """Create the watch rule from wizard state and clean up."""
        wizard = self._addrule_wizards.get(user_id)
        if wizard is None:
            await event.edit("Wizard session lost. Use /addrule to start again.")
            return

        rule_name = getattr(wizard, "_pending_name", None)
        if not rule_name:
            await event.edit("No rule name captured. Use /addrule to start again.")
            return

        if wizard.is_timed_out():
            del self._addrule_wizards[user_id]
            await event.edit("Wizard timed out. Use /addrule to start again.")
            return

        # Build the WatchRule
        try:
            from hkjc_scrapper.models import (
                MatchFilter, Observation, Schedule, ScheduleTrigger, WatchRule
            )
            from pymongo.errors import DuplicateKeyError

            if wizard.schedule_mode == "event":
                schedule = Schedule(
                    mode="event",
                    triggers=[ScheduleTrigger(
                        event=wizard.trigger_event,
                        minutes=wizard.trigger_minutes or None,
                    )],
                )
            else:
                schedule = Schedule(
                    mode="continuous",
                    interval_seconds=wizard.interval_seconds,
                    start_event=wizard.start_event,
                    end_event=wizard.end_event,
                )

            rule = WatchRule(
                name=rule_name,
                enabled=True,
                match_filter=MatchFilter(tournaments=wizard.tournaments),
                observations=[Observation(
                    odds_types=wizard.odds_types,
                    schedule=schedule,
                )],
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.db.add_watch_rule(rule))
            del self._addrule_wizards[user_id]
            await event.edit(
                f"Rule <b>{rule_name}</b> created successfully!",
                parse_mode="html"
            )
        except Exception as e:
            await event.edit(f"Error creating rule: {e}")
