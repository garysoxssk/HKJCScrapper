"""Configuration settings using pydantic-settings.

Supports environment profiles via APP_ENV:
  APP_ENV=local  -> loads .env.local then .env (default)
  APP_ENV=prod   -> loads .env.prod then .env

Set APP_ENV as an OS environment variable before starting.
"""

import os
from functools import cached_property
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Determine which profile to load
_APP_ENV = os.environ.get("APP_ENV", "local")
_ENV_FILES = (f".env.{_APP_ENV}", ".env")


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env files."""

    # Profile
    APP_ENV: str = "local"

    # MongoDB settings
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "hkjc"
    MONGODB_USER: str = ""
    MONGODB_PASSWORD: str = ""
    MONGODB_HOST: str = ""  # e.g. "scrapperdbcluster.twnkirh.mongodb.net"

    @model_validator(mode="after")
    def _build_mongodb_uri(self) -> "Settings":
        """If MONGODB_HOST is set, build the Atlas URI from parts.

        This allows the password to be passed as a separate env var
        without shell variable expansion in .env files.
        """
        if self.MONGODB_HOST and self.MONGODB_USER and self.MONGODB_PASSWORD:
            pwd = quote_plus(self.MONGODB_PASSWORD)
            self.MONGODB_URI = (
                f"mongodb+srv://{self.MONGODB_USER}:{pwd}"
                f"@{self.MONGODB_HOST}/?appName=scrapperDBCluster"
            )
        return self

    # HKJC API settings
    GRAPHQL_ENDPOINT: str = "https://info.cld.hkjc.com/graphql/base/"

    # Scheduler settings
    DISCOVERY_INTERVAL_SECONDS: int = 900  # 15 minutes

    # Pagination settings
    START_INDEX: int = 1
    END_INDEX: int = 60

    # Telegram notifications
    TELEGRAM_ENABLED: bool = True
    TELEGRAM_APP_ID: int = 0
    TELEGRAM_API_KEY: str = ""
    TELEGRAM_GROUP_ID: str = ""
    TELEGRAM_SESSION_NAME: str = "hkjc_scrapper_msg_bot"
    TELEGRAM_BOT_TOKEN: str = ""

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )
