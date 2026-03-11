"""Configuration settings using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or defaults."""

    # MongoDB settings
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "hkjc"

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
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )
