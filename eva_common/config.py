"""
EVA-Finance Centralized Configuration

Uses Pydantic BaseSettings for validated, type-safe configuration.
Supports both DATABASE_URL and individual POSTGRES_* environment variables.

Usage:
    from eva_common.config import settings

    print(settings.connection_url)  # Full database URL
    print(settings.db_pool_max)     # Pool configuration
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import computed_field, model_validator


class DatabaseSettings(BaseSettings):
    """
    Database configuration with support for multiple env var patterns.

    Priority:
    1. DATABASE_URL (if set, used directly)
    2. Individual POSTGRES_* variables (fallback)
    """

    # Direct URL takes precedence (used by eva-api, worker.py)
    database_url: Optional[str] = None

    # Individual components - fallback pattern
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "eva_finance"
    postgres_user: str = "eva"
    postgres_password: Optional[str] = None  # Optional if database_url provided

    # Connection pool settings
    db_pool_min: int = 2
    db_pool_max: int = 10

    @model_validator(mode='after')
    def check_password_or_url(self) -> 'DatabaseSettings':
        """Ensure either database_url or postgres_password is provided."""
        if not self.database_url and not self.postgres_password:
            raise ValueError('Either database_url or postgres_password must be provided')
        return self

    @computed_field
    @property
    def connection_url(self) -> str:
        """
        Returns the database connection URL.
        Uses DATABASE_URL if set, otherwise builds from individual vars.
        """
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # Ignore extra env vars like OPENAI_API_KEY
    }


class AppSettings(BaseSettings):
    """
    Application-level settings (non-database).
    """

    # OpenAI
    openai_api_key: Optional[str] = None
    eva_model: str = "gpt-4o-mini"

    # Notifications
    ntfy_url: str = "http://eva_ntfy:80"
    notification_poll_interval: int = 60

    # Google Trends
    google_trends_enabled: bool = True
    google_trends_cache_hours: int = 24
    google_trends_min_confidence: float = 0.60
    google_trends_rate_limit_per_hour: int = 60

    # Financial Modeling Prep API (brand-ticker mapping)
    fmp_api_key: Optional[str] = None
    fmp_enabled: bool = True
    fmp_rate_limit_ms: int = 500  # Minimum ms between API calls

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton instances - import these directly
db_settings = DatabaseSettings()
app_settings = AppSettings()

# Convenience alias for backward compatibility
settings = db_settings
