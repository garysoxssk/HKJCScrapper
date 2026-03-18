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

    def test_notify_fetch(self, enabled_settings):
        with patch.object(TGMessageClient, "_start_event_loop_thread"):
            client = TGMessageClient(enabled_settings)
            client.send_sync = MagicMock()

            client.notify_fetch("FB4233", "Liverpool", "Arsenal", ["HAD", "HHA"], 2)
            msg = client.send_sync.call_args[0][0]
            assert "Odds Fetched" in msg
            assert "Liverpool" in msg
            assert "HAD, HHA" in msg

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
