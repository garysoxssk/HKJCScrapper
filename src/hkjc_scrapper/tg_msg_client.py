"""Telegram notification client for HKJC Scrapper.

Sends structured messages to a Telegram group/channel for:
- Scheduler events (discovery, match scheduling, fetch completion)
- CLI operations (rule changes, ad-hoc fetches)
- Custom one-off messages

Uses Telethon (MTProto) for sending. All sends are fire-and-forget:
failures are logged but never crash the caller.
"""

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from telethon import TelegramClient
from telethon.tl.custom.message import Message

from hkjc_scrapper.config import Settings

logger = logging.getLogger(__name__)


def _parse_group_id(raw: str) -> int | str:
    """Parse TELEGRAM_GROUP_ID into a numeric ID or username string.

    Bots CANNOT resolve invite links (https://t.me/+XXX).
    They need either:
      - Numeric chat ID (e.g., -1001234567890)
      - Username (e.g., @my_channel)

    Args:
        raw: The TELEGRAM_GROUP_ID value from config

    Returns:
        int for numeric IDs, str for usernames

    Raises:
        ValueError: If the format is an invite link (unsupported for bots)
    """
    stripped = raw.strip()

    # Numeric ID (e.g., "-1001234567890")
    try:
        return int(stripped)
    except ValueError:
        pass

    # Invite link -- bots can't use these
    if "t.me/+" in stripped or "/joinchat/" in stripped:
        raise ValueError(
            f"Bots cannot resolve invite links: {stripped}. "
            "Use the numeric chat ID instead (e.g., -1001234567890). "
            "To find it, add @userinfobot to your group or use "
            "'client.get_entity()' from a user session."
        )

    # Username (e.g., "@my_channel" or "my_channel")
    return stripped


class TGMessageClient:
    """Telegram notification client with persistent connection and dedicated event loop.

    Two-phase initialization:
      1. __init__() — stores config, no background thread started yet
      2. enable_commands(db, api_client) — optional, call before start() if TG_COMMANDS_ENABLED
      3. start() — starts the background thread and connects to Telegram
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self._enabled = (
            self.settings.TELEGRAM_ENABLED
            and self.settings.TELEGRAM_APP_ID > 0
            and bool(self.settings.TELEGRAM_API_KEY)
            and bool(self.settings.TELEGRAM_GROUP_ID)
        )
        self._client: Optional[TelegramClient] = None
        self._entity = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._shutdown = threading.Event()
        # Command handler — set via enable_commands() before start()
        self._cmd_db = None
        self._cmd_api = None
        self._cmd_handler = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ========================================================================
    # Two-phase startup
    # ========================================================================

    def enable_commands(self, db, api_client) -> None:
        """Enable interactive command handling. Must be called before start().

        Stores the db and api_client references. The actual TGCommandHandler
        is created in _async_init() once the TelegramClient is available.

        Args:
            db: MongoDBClient instance
            api_client: HKJCGraphQLClient instance
        """
        self._cmd_db = db
        self._cmd_api = api_client

    def start(self) -> None:
        """Start the background event loop thread and connect to Telegram.

        Call after enable_commands() (if using command mode) and before any send_sync calls.
        """
        if self._enabled:
            self._start_event_loop_thread()

    # ========================================================================
    # Thread-based event loop management
    # ========================================================================

    def _start_event_loop_thread(self) -> None:
        """Start a dedicated background thread with its own event loop."""

        def run_loop():
            """Thread target: create loop, initialize client, run until disconnected."""
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            try:
                self._loop.run_until_complete(self._async_init())
                self._ready.set()

                # run_until_disconnected keeps the loop alive AND processes
                # incoming events (commands, callbacks) if handlers are registered
                self._loop.run_until_complete(self._client.run_until_disconnected())
            except Exception:
                logger.exception("[TG] Event loop thread crashed")
                self._ready.set()  # Unblock waiting threads even on error
            finally:
                # Properly disconnect before closing loop
                if self._client and self._client.is_connected():
                    try:
                        self._loop.run_until_complete(self._client.disconnect())
                    except Exception:
                        pass
                self._loop.close()

        self._thread = threading.Thread(
            target=run_loop, daemon=True, name="TGMessageLoop"
        )
        self._thread.start()
        self._ready.wait(timeout=15)

        # Check if init succeeded
        if not self._entity:
            if self._enabled:
                logger.error("[TG] Failed to connect, notifications disabled")
            self._enabled = False

    async def _async_init(self) -> None:
        """Initialize Telethon client (runs in dedicated thread's loop)."""
        self._client = TelegramClient(
            self.settings.TELEGRAM_SESSION_NAME,
            self.settings.TELEGRAM_APP_ID,
            self.settings.TELEGRAM_API_KEY,
        )

        if self.settings.TELEGRAM_BOT_TOKEN:
            await self._client.start(bot_token=self.settings.TELEGRAM_BOT_TOKEN)
        else:
            await self._client.start()

        # Resolve the target group entity
        target = _parse_group_id(self.settings.TELEGRAM_GROUP_ID)
        self._entity = await self._client.get_entity(target)
        logger.info("[TG] Connected (group: %s)", self.settings.TELEGRAM_GROUP_ID)

        # Register command handlers if enable_commands() was called
        if self._cmd_db is not None:
            from hkjc_scrapper.tg_commands import TGCommandHandler
            self._cmd_handler = TGCommandHandler(
                self._client, self._cmd_db, self._cmd_api, self.settings
            )
            self._cmd_handler.register_handlers()
            logger.info("[TG] Command handlers registered")

    # ========================================================================
    # Core send (async - runs in dedicated loop via thread-safe call)
    # ========================================================================

    async def _reconnect(self) -> bool:
        """Attempt to reconnect the Telethon client after a connection loss.

        Returns True if reconnection succeeded.
        """
        try:
            logger.info("[TG] Attempting reconnect...")
            if not self._client.is_connected():
                await self._client.connect()
            # Re-resolve entity in case session state is stale
            target = _parse_group_id(self.settings.TELEGRAM_GROUP_ID)
            self._entity = await self._client.get_entity(target)
            logger.info("[TG] Reconnected successfully")
            return True
        except Exception:
            logger.warning("[TG] Reconnect failed")
            return False

    async def send_message_async(
        self, message: str, parse_mode: str = "html"
    ) -> Optional[Message]:
        """Send a message asynchronously with auto-reconnect on failure."""
        if not self._enabled or not self._client:
            return None

        for attempt in range(2):  # Try once, reconnect, try again
            try:
                return await self._client.send_message(
                    self._entity, message, parse_mode=parse_mode
                )
            except Exception:
                if attempt == 0:
                    logger.warning("[TG] Send failed, attempting reconnect...")
                    if await self._reconnect():
                        continue  # Retry after reconnect
                logger.exception("[TG] Failed to send message after reconnect")
                return None
        return None

    # ========================================================================
    # Sync wrapper (for use from sync code like scheduler/CLI)
    # ========================================================================

    def send_sync(self, message: str, parse_mode: str = "html") -> None:
        """Send a message synchronously. Safe to call from sync context.

        Submits the message to the dedicated event loop thread. Never raises.
        """
        if not self._enabled or not self._loop:
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                self.send_message_async(message, parse_mode), self._loop
            )
            future.result(timeout=10)
        except Exception:
            logger.exception("[TG] Failed to send sync message")

    def close(self) -> None:
        """Close the client and cleanup (call on shutdown)."""
        if not self._thread:
            return

        logger.info("[TG] Shutting down...")
        self._shutdown.set()

        # Disconnect the client to break run_until_disconnected()
        if self._loop and self._client:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._client.disconnect(), self._loop
                )
                future.result(timeout=5)
            except Exception:
                pass

        if self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("[TG] Shutdown complete")

    # ========================================================================
    # Structured message builders
    # ========================================================================

    def notify_discovery(
        self,
        match_count: int,
        rule_count: int,
        jobs_scheduled: int,
        rule_details: list[dict] | None = None,
    ) -> None:
        """Notify about a discovery cycle result.

        Args:
            match_count: Total matches found from HKJC API
            rule_count: Number of active watch rules
            jobs_scheduled: Number of new fetch jobs scheduled
            rule_details: Optional per-rule breakdown. Each dict:
                {"name": str, "matched": int, "jobs": int}
        """
        msg = (
            "<b>Discovery Complete</b>\n"
            f"Matches found: {match_count}\n"
            f"Active rules: {rule_count}\n"
            f"New jobs scheduled: {jobs_scheduled}"
        )
        if rule_details:
            msg += "\n\n<b>Rules matched:</b>"
            for rd in rule_details:
                msg += (
                    f"\n• {rd['name']}: "
                    f"{rd['matched']} match(es), {rd['jobs']} job(s)"
                )
        self.send_sync(msg)

    def notify_fetch(
        self,
        front_end_id: str,
        home: str,
        away: str,
        odds_types: list[str],
        odds_snapshots: int,
        odds_details: list[dict] | None = None,
    ) -> None:
        """Notify about a completed fetch + save.

        Args:
            front_end_id: Match front-end ID (e.g., FB4233)
            home: Home team name
            away: Away team name
            odds_types: List of odds type codes fetched
            odds_snapshots: Number of snapshots saved
            odds_details: Optional list of pool dicts with all line odds.
                Each dict: {"oddsType": str, "lines": [{"condition": str|None,
                "main": bool, "combinations": [{"str": str, "currentOdds": str}]}]}
        """
        odds_str = ", ".join(odds_types)
        msg = (
            f"<b>Odds Fetched</b>\n"
            f"<b>{home}</b> vs <b>{away}</b> ({front_end_id})\n"
            f"Types: {odds_str}\n"
            f"Snapshots saved: {odds_snapshots}"
        )
        if odds_details:
            msg += "\n"
            for detail in odds_details:
                msg += f"\n{self._format_pool_odds(detail)}"
            # Truncate if too long (Telegram limit is 4096)
            if len(msg) > 3500:
                msg = msg[:3497] + "..."
        self.send_sync(msg)

    @staticmethod
    def _format_pool_odds(detail: dict) -> str:
        """Format one pool's odds (all lines) as a compact HTML string.

        Args:
            detail: Pool dict with oddsType and lines list

        Returns:
            Formatted string like "<b>HHA</b>:\n  [-1.5] H=1.85 | A=1.95 (main)\n  [-2.0] H=2.10 | A=1.70"
        """
        odds_type = detail.get("oddsType", "?")
        lines = detail.get("lines", [])
        parts = [f"<b>{odds_type}</b>:"]
        for line in lines:
            condition = line.get("condition")
            is_main = line.get("main", False)
            combinations = line.get("combinations", [])
            comb_str = " | ".join(
                f"{c.get('str', '?')}={c.get('currentOdds', '?')}"
                for c in combinations
            )
            cond_prefix = f"[{condition}] " if condition else ""
            main_suffix = " (main)" if is_main else ""
            parts.append(f"  {cond_prefix}{comb_str}{main_suffix}")
        return "\n".join(parts)

    def notify_scheduled(
        self,
        front_end_id: str,
        home: str,
        away: str,
        odds_key: str,
        trigger_desc: str,
        trigger_time_str: str,
    ) -> None:
        """Notify about a newly scheduled fetch job."""
        msg = (
            f"<b>Job Scheduled</b>\n"
            f"<b>{home}</b> vs <b>{away}</b> ({front_end_id})\n"
            f"Odds: {odds_key}\n"
            f"Trigger: {trigger_desc} at {trigger_time_str}"
        )
        self.send_sync(msg)

    def notify_rule_change(
        self, action: str, rule_name: str, detail: str = ""
    ) -> None:
        """Notify about a watch rule change (add/enable/disable/delete)."""
        msg = f"<b>Rule {action.title()}</b>: {rule_name}"
        if detail:
            msg += f"\n{detail}"
        self.send_sync(msg)

    def notify_startup(self, mode: str, rule_count: int) -> None:
        """Notify about service startup."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        msg = (
            f"<b>HKJCScrapper Started</b>\n"
            f"Mode: {mode}\n"
            f"Active rules: {rule_count}\n"
            f"Time: {now}"
        )
        self.send_sync(msg)

    def notify_custom(self, message: str) -> None:
        """Send a custom plain-text message."""
        self.send_sync(message)

    def notify_error(self, context: str, error: Exception) -> None:
        """Notify about an error during a scheduled operation.

        Args:
            context: Short description of what was running (e.g., "Discovery cycle")
            error: The exception that was raised
        """
        error_str = str(error)
        if len(error_str) > 200:
            error_str = error_str[:200] + "..."
        msg = (
            f"<b>⚠️ Error</b>: {context}\n"
            f"<code>{error_str}</code>"
        )
        self.send_sync(msg)
