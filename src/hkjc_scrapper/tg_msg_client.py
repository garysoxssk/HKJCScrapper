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
    """Telegram notification client with persistent connection and dedicated event loop."""

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

        if self._enabled:
            self._start_event_loop_thread()

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ========================================================================
    # Thread-based event loop management
    # ========================================================================

    def _start_event_loop_thread(self) -> None:
        """Start a dedicated background thread with its own event loop."""

        def run_loop():
            """Thread target: create loop, initialize client, run forever."""
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            try:
                self._loop.run_until_complete(self._async_init())
                self._ready.set()

                # Keep loop running for future messages
                while not self._shutdown.is_set():
                    self._loop.run_until_complete(asyncio.sleep(0.1))
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

    # ========================================================================
    # Core send (async - runs in dedicated loop via thread-safe call)
    # ========================================================================

    async def send_message_async(
        self, message: str, parse_mode: str = "html"
    ) -> Optional[Message]:
        """Send a message asynchronously (internal use)."""
        if not self._enabled or not self._client:
            return None

        try:
            return await self._client.send_message(
                self._entity, message, parse_mode=parse_mode
            )
        except Exception:
            logger.exception("[TG] Failed to send message")
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

        if self._loop and self._client and self._client.is_connected():
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
        self, match_count: int, rule_count: int, jobs_scheduled: int
    ) -> None:
        """Notify about a discovery cycle result."""
        msg = (
            "<b>Discovery Complete</b>\n"
            f"Matches found: {match_count}\n"
            f"Active rules: {rule_count}\n"
            f"New jobs scheduled: {jobs_scheduled}"
        )
        self.send_sync(msg)

    def notify_fetch(
        self,
        front_end_id: str,
        home: str,
        away: str,
        odds_types: list[str],
        odds_snapshots: int,
    ) -> None:
        """Notify about a completed fetch + save."""
        odds_str = ", ".join(odds_types)
        msg = (
            f"<b>Odds Fetched</b>\n"
            f"<b>{home}</b> vs <b>{away}</b> ({front_end_id})\n"
            f"Types: {odds_str}\n"
            f"Snapshots saved: {odds_snapshots}"
        )
        self.send_sync(msg)

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
