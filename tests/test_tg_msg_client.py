"""Unit tests for tg_msg_client.py using mocked Telethon client."""

from unittest.mock import MagicMock, patch

import pytest

from hkjc_scrapper.config import Settings
from hkjc_scrapper.tg_msg_client import TGMessageClient, _parse_group_id


@pytest.fixture
def disabled_settings():
    """Settings with Telegram disabled."""
    s = Settings()
    s.TELEGRAM_ENABLED = False
    return s


@pytest.fixture
def enabled_settings():
    """Settings with Telegram enabled and dummy credentials."""
    s = Settings()
    s.TELEGRAM_ENABLED = True
    s.TELEGRAM_APP_ID = 12345
    s.TELEGRAM_API_KEY = "fake_key"
    s.TELEGRAM_GROUP_ID = "-1001234567890"
    s.TELEGRAM_BOT_TOKEN = "123:fake_bot_token"
    return s


# ============================================================================
# _parse_group_id tests
# ============================================================================

class TestParseGroupId:

    def test_numeric_id(self):
        assert _parse_group_id("-1001234567890") == -1001234567890

    def test_numeric_id_positive(self):
        assert _parse_group_id("12345") == 12345

    def test_username_with_at(self):
        assert _parse_group_id("@my_channel") == "@my_channel"

    def test_username_without_at(self):
        assert _parse_group_id("my_channel") == "my_channel"

    def test_invite_link_raises(self):
        with pytest.raises(ValueError, match="Bots cannot resolve invite links"):
            _parse_group_id("https://t.me/+U78Q8BXFAK1lYmNl")

    def test_joinchat_link_raises(self):
        with pytest.raises(ValueError, match="Bots cannot resolve invite links"):
            _parse_group_id("https://t.me/joinchat/ABCDEF")

    def test_strips_whitespace(self):
        assert _parse_group_id("  -1001234567890  ") == -1001234567890


# ============================================================================
# TGMessageClient init tests
# ============================================================================

class TestTGMessageClientInit:

    def test_disabled_when_flag_off(self, disabled_settings):
        client = TGMessageClient(disabled_settings)
        assert client.enabled is False

    def test_disabled_when_no_app_id(self):
        s = Settings()
        s.TELEGRAM_ENABLED = True
        s.TELEGRAM_APP_ID = 0
        s.TELEGRAM_API_KEY = "key"
        s.TELEGRAM_GROUP_ID = "-100123"
        client = TGMessageClient(s)
        assert client.enabled is False

    def test_disabled_when_no_api_key(self):
        s = Settings()
        s.TELEGRAM_ENABLED = True
        s.TELEGRAM_APP_ID = 123
        s.TELEGRAM_API_KEY = ""
        s.TELEGRAM_GROUP_ID = "-100123"
        client = TGMessageClient(s)
        assert client.enabled is False

    def test_disabled_when_no_group_id(self):
        s = Settings()
        s.TELEGRAM_ENABLED = True
        s.TELEGRAM_APP_ID = 123
        s.TELEGRAM_API_KEY = "key"
        s.TELEGRAM_GROUP_ID = ""
        client = TGMessageClient(s)
        assert client.enabled is False

    def test_enabled_with_all_fields(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            assert client._enabled is True


# ============================================================================
# send_sync tests
# ============================================================================

class TestTGMessageClientSendSync:

    def test_send_sync_skips_when_disabled(self, disabled_settings):
        client = TGMessageClient(disabled_settings)
        client.send_sync("test message")

    def test_send_sync_does_not_crash_on_error(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client._loop = None
            client.send_sync("test message")


# ============================================================================
# Structured notification tests
# ============================================================================

class TestTGMessageClientNotify:

    def test_notify_discovery(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_discovery(84, 3, 5)
            client.send_sync.assert_called_once()
            msg = client.send_sync.call_args[0][0]
            assert "Discovery Complete" in msg
            assert "84" in msg
            assert "5" in msg

    def test_notify_discovery_without_rule_details(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_discovery(84, 3, 5)
            client.send_sync.assert_called_once()
            msg = client.send_sync.call_args[0][0]
            assert "Discovery Complete" in msg
            assert "84" in msg
            assert "5" in msg
            assert "Rules matched" not in msg

    def test_notify_discovery_with_rule_details(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            rule_details = [
                {"name": "EPL HAD", "matched": 3, "jobs": 5},
                {"name": "La Liga CHL", "matched": 2, "jobs": 2},
            ]
            client.notify_discovery(84, 3, 5, rule_details=rule_details)
            msg = client.send_sync.call_args[0][0]
            assert "Discovery Complete" in msg
            assert "Rules matched" in msg
            assert "EPL HAD" in msg
            assert "3 match" in msg
            assert "5 job" in msg
            assert "La Liga CHL" in msg

    def test_notify_fetch(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_fetch("FB4233", "Liverpool", "Arsenal", ["HAD", "HHA"], 2)
            msg = client.send_sync.call_args[0][0]
            assert "Odds Fetched" in msg
            assert "Liverpool" in msg
            assert "HAD, HHA" in msg

    def test_notify_fetch_without_odds_details(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_fetch("FB4233", "Liverpool", "Arsenal", ["HAD"], 2)
            msg = client.send_sync.call_args[0][0]
            assert "Odds Fetched" in msg
            assert "Liverpool" in msg
            assert "HAD" in msg
            # No odds block appended
            assert "<b>HAD</b>:" not in msg

    def test_notify_fetch_with_odds_details(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            odds_details = [
                {
                    "oddsType": "HAD",
                    "lines": [
                        {
                            "condition": None,
                            "main": True,
                            "combinations": [
                                {"str": "H", "currentOdds": "2.50"},
                                {"str": "D", "currentOdds": "3.20"},
                                {"str": "A", "currentOdds": "2.80"},
                            ],
                        }
                    ],
                }
            ]
            client.notify_fetch("FB4233", "Liverpool", "Arsenal", ["HAD"], 2, odds_details=odds_details)
            msg = client.send_sync.call_args[0][0]
            assert "Odds Fetched" in msg
            assert "<b>HAD</b>:" in msg
            assert "H=2.50" in msg
            assert "D=3.20" in msg
            assert "(main)" in msg

    def test_notify_fetch_odds_truncated_at_3500(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            # Create many pools to exceed 3500 chars
            odds_details = [
                {
                    "oddsType": f"T{i:02d}",
                    "lines": [
                        {
                            "condition": f"-{i}.5",
                            "main": True,
                            "combinations": [
                                {"str": "H", "currentOdds": "1.85"},
                                {"str": "A", "currentOdds": "1.95"},
                            ],
                        }
                    ],
                }
                for i in range(100)
            ]
            client.notify_fetch("FB4233", "Team A", "Team B", ["HAD"], 2, odds_details=odds_details)
            msg = client.send_sync.call_args[0][0]
            assert len(msg) <= 3500
            assert msg.endswith("...")

    def test_format_pool_odds_with_condition(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            detail = {
                "oddsType": "HHA",
                "lines": [
                    {"condition": "-1.5", "main": True, "combinations": [
                        {"str": "H", "currentOdds": "1.85"},
                        {"str": "A", "currentOdds": "1.95"},
                    ]},
                    {"condition": "-2.0", "main": False, "combinations": [
                        {"str": "H", "currentOdds": "2.10"},
                        {"str": "A", "currentOdds": "1.70"},
                    ]},
                ],
            }
            result = client._format_pool_odds(detail)
            assert "<b>HHA</b>:" in result
            assert "[-1.5]" in result
            assert "(main)" in result
            assert "[-2.0]" in result
            assert "(main)" not in result.split("[-2.0]")[1].split("\n")[0]

    def test_notify_rule_change(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_rule_change("added", "EPL HAD", "Tournaments: EPL")
            msg = client.send_sync.call_args[0][0]
            assert "Rule Added" in msg
            assert "EPL HAD" in msg

    def test_notify_startup(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_startup("service", 3)
            msg = client.send_sync.call_args[0][0]
            assert "HKJCScrapper Started" in msg
            assert "service" in msg

    def test_notify_custom(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_custom("Hello from HKJC bot!")
            client.send_sync.assert_called_once_with("Hello from HKJC bot!")

    def test_notify_error(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_error("Discovery cycle", ValueError("Connection refused"))
            client.send_sync.assert_called_once()
            msg = client.send_sync.call_args[0][0]
            assert "Error" in msg
            assert "Discovery cycle" in msg
            assert "Connection refused" in msg

    def test_notify_error_truncation(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            long_error = ValueError("x" * 300)
            client.notify_error("Fetch FB4233", long_error)
            msg = client.send_sync.call_args[0][0]
            # Message should contain truncated error (200 chars + "...")
            assert "..." in msg
            assert "Fetch FB4233" in msg


# ============================================================================
# Two-phase init tests (Enhancement 4)
# ============================================================================

class TestTGMessageClientTwoPhaseInit:

    def test_init_does_not_start_thread(self, enabled_settings):
        """After __init__ alone, no background thread is running."""
        with patch.object(TGMessageClient, "_start_event_loop_thread") as mock_start:
            client = TGMessageClient(enabled_settings)
            mock_start.assert_not_called()
            assert client._thread is None

    def test_start_calls_start_event_loop_thread(self, enabled_settings):
        """start() triggers _start_event_loop_thread when enabled."""
        with patch.object(TGMessageClient, "_start_event_loop_thread") as mock_start:
            client = TGMessageClient(enabled_settings)
            client.start()
            mock_start.assert_called_once()

    def test_start_does_nothing_when_disabled(self, disabled_settings):
        """start() on a disabled client does nothing."""
        with patch.object(TGMessageClient, "_start_event_loop_thread") as mock_start:
            client = TGMessageClient(disabled_settings)
            client.start()
            mock_start.assert_not_called()

    def test_enable_commands_sets_db_and_api(self, enabled_settings):
        """enable_commands() stores db and api_client references."""
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            mock_db = MagicMock()
            mock_api = MagicMock()
            client.enable_commands(mock_db, mock_api)
            assert client._cmd_db is mock_db
            assert client._cmd_api is mock_api

    def test_enable_commands_without_start_backward_compat(self, disabled_settings):
        """enable_commands on disabled client is safe (no-op for start)."""
        client = TGMessageClient(disabled_settings)
        mock_db = MagicMock()
        mock_api = MagicMock()
        client.enable_commands(mock_db, mock_api)
        client.start()  # Should not raise

    def test_close_calls_disconnect(self, enabled_settings):
        """close() calls client.disconnect() to break run_until_disconnected."""
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.start()
            # Set up a mock client and loop
            mock_tg_client = MagicMock()
            mock_tg_client.disconnect = MagicMock(return_value=None)
            mock_loop = MagicMock()
            mock_future = MagicMock()
            mock_future.result = MagicMock(return_value=None)
            client._client = mock_tg_client
            client._loop = mock_loop
            client._thread = MagicMock()
            client._thread.is_alive.return_value = False
            with patch("asyncio.run_coroutine_threadsafe", return_value=mock_future) as mock_rctf:
                client.close()
                mock_rctf.assert_called()


# ============================================================================
# CLI integration tests
# ============================================================================

class TestTGCLIIntegration:

    def test_add_rule_notifies(self, mock_db):
        from hkjc_scrapper.cli import cmd_add_rule

        class FakeArgs:
            name = "Test Rule"
            teams = "Liverpool"
            tournaments = "EPL"
            match_ids = ""
            observation = ["HAD:event:at_kickoff"]

        tg = MagicMock()
        tg.enabled = True
        result = cmd_add_rule(FakeArgs(), mock_db, tg=tg)
        assert result == 0
        tg.notify_rule_change.assert_called_once()

    def test_enable_rule_notifies(self, mock_db, sample_watch_rule):
        from hkjc_scrapper.cli import cmd_enable_rule

        sample_watch_rule.enabled = False
        mock_db.add_watch_rule(sample_watch_rule)

        class FakeArgs:
            name = "Test EPL Rule"

        tg = MagicMock()
        tg.enabled = True
        result = cmd_enable_rule(FakeArgs(), mock_db, tg=tg)
        assert result == 0
        tg.notify_rule_change.assert_called_once()

    def test_send_message_calls_tg(self, mock_db):
        from hkjc_scrapper.cli import cmd_send_message

        class FakeArgs:
            message = "Hello World"

        tg = MagicMock()
        tg.enabled = True
        result = cmd_send_message(FakeArgs(), mock_db, tg=tg)
        assert result == 0
        tg.notify_custom.assert_called_once_with("Hello World")

    def test_send_message_fails_when_disabled(self, mock_db, capsys):
        from hkjc_scrapper.cli import cmd_send_message

        class FakeArgs:
            message = "Hello"

        result = cmd_send_message(FakeArgs(), mock_db, tg=None)
        assert result == 1
        assert "not enabled" in capsys.readouterr().out
