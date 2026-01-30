# EVA-Finance Config Management

## Overview

EVA-Finance uses **Pydantic Settings** for type-safe, validated configuration management. All configuration flows through the `eva_common` package.

## Configuration Hierarchy

```
.env file
    ↓
Environment Variables
    ↓
Pydantic Settings (eva_common/config.py)
    ↓
Singleton Instances (db_settings, app_settings)
    ↓
Service Code
```

## Environment Variables

### Required Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgres://eva:pass@db:5432/eva_finance` | Full database URL |
| `POSTGRES_PASSWORD` | `eva_password_change_me` | DB password (if not using DATABASE_URL) |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `db` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |
| `POSTGRES_DB` | `eva_finance` | Database name |
| `POSTGRES_USER` | `eva` | Database user |
| `DB_POOL_MIN` | `2` | Minimum pool connections |
| `DB_POOL_MAX` | `10` | Maximum pool connections |
| `OPENAI_API_KEY` | None | OpenAI API key for LLM extraction |
| `EVA_MODEL` | `gpt-4o-mini` | OpenAI model to use |
| `NTFY_URL` | `http://eva_ntfy:80` | Notification service URL |
| `NOTIFICATION_POLL_INTERVAL` | `60` | Seconds between notification polls |
| `GOOGLE_TRENDS_ENABLED` | `true` | Enable Google Trends validation |
| `GOOGLE_TRENDS_CACHE_HOURS` | `24` | Hours to cache trends data |
| `GOOGLE_TRENDS_MIN_CONFIDENCE` | `0.60` | Min confidence for trends check |

## .env File Structure

```bash
# .env.example

# OpenAI (required for LLM extraction, optional for fallback mode)
OPENAI_API_KEY=sk-proj-your-key-here
EVA_MODEL=gpt-4o-mini

# Database - Option 1: Full URL (recommended)
DATABASE_URL=postgres://eva:eva_password_change_me@db:5432/eva_finance

# Database - Option 2: Individual components (alternative)
POSTGRES_USER=eva
POSTGRES_PASSWORD=eva_password_change_me
POSTGRES_DB=eva_finance

# Google Trends Cross-Validation
GOOGLE_TRENDS_ENABLED=true
GOOGLE_TRENDS_CACHE_HOURS=24
GOOGLE_TRENDS_MIN_CONFIDENCE=0.60
GOOGLE_TRENDS_RATE_LIMIT_PER_HOUR=60

# Reddit Ingestion (optional - defaults to http://eva-api:8080/intake/message)
# EVA_API_URL=http://localhost:9080/intake/message
```

## Config Loading Code (eva_common/config.py)

```python
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
    postgres_password: Optional[str] = None

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
    """Application-level settings (non-database)."""

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
```

## Usage Patterns

### Accessing Database Config

```python
from eva_common.config import db_settings

# Get connection URL
url = db_settings.connection_url

# Get pool settings
pool_min = db_settings.db_pool_min
pool_max = db_settings.db_pool_max
```

### Accessing Application Config

```python
from eva_common.config import app_settings

# OpenAI settings
api_key = app_settings.openai_api_key
model = app_settings.eva_model

# Notification settings
ntfy_url = app_settings.ntfy_url
poll_interval = app_settings.notification_poll_interval

# Google Trends settings
trends_enabled = app_settings.google_trends_enabled
cache_hours = app_settings.google_trends_cache_hours
```

### In Worker Code

```python
from eva_common.config import app_settings

# Configure logging
logger = logging.getLogger(__name__)

# Configuration from eva_common
MODEL_NAME = app_settings.eva_model
NOTIFICATION_POLL_INTERVAL = app_settings.notification_poll_interval

client = OpenAI(api_key=app_settings.openai_api_key) if app_settings.openai_api_key else None
```

### Environment-Based Thresholds

Some configuration uses `os.getenv()` directly for threshold tuning:

```python
import os

# Adaptive thresholds for Phase 0 (early-stage data)
INTENT_THRESHOLD = float(os.getenv("EVA_GATE_INTENT", "0.50"))
SUPPRESSION_THRESHOLD = float(os.getenv("EVA_GATE_SUPPRESSION", "0.40"))
SPREAD_THRESHOLD = float(os.getenv("EVA_GATE_SPREAD", "0.25"))

# Band thresholds
HIGH_THRESHOLD = float(os.getenv("EVA_BAND_HIGH", "0.60"))
WATCHLIST_THRESHOLD = float(os.getenv("EVA_BAND_WATCHLIST", "0.50"))
```

## Docker Compose Environment

### Service-Level Environment

```yaml
services:
  eva-api:
    environment:
      DATABASE_URL: ${DATABASE_URL}

  eva-worker:
    env_file:
      - .env
    environment:
      NOTIFICATION_POLL_INTERVAL: 60
      NTFY_URL: http://eva_ntfy:80

  eva-ai-infrastructure-worker:
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - AI_INFRA_ENABLED=true
```

### Database Service Environment

```yaml
  db:
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
```

## Validation Rules

### Database Config

- Either `DATABASE_URL` or `POSTGRES_PASSWORD` must be provided
- If `DATABASE_URL` is set, it takes precedence
- Pool settings must be positive integers

### Pydantic Validation

```python
@model_validator(mode='after')
def check_password_or_url(self) -> 'DatabaseSettings':
    """Ensure either database_url or postgres_password is provided."""
    if not self.database_url and not self.postgres_password:
        raise ValueError('Either database_url or postgres_password must be provided')
    return self
```

## Adding New Config

1. **Add to appropriate Settings class**:

```python
class AppSettings(BaseSettings):
    # Existing settings...

    # New feature settings
    new_feature_enabled: bool = False
    new_feature_threshold: float = 0.75
```

2. **Add to .env.example**:

```bash
# New Feature
NEW_FEATURE_ENABLED=false
NEW_FEATURE_THRESHOLD=0.75
```

3. **Use in code**:

```python
from eva_common.config import app_settings

if app_settings.new_feature_enabled:
    threshold = app_settings.new_feature_threshold
    ...
```

## Security Notes

- Never commit `.env` files with real credentials
- Use `.env.example` for documentation
- Check for credential leaks before commits:

```bash
grep -r "sk-\|postgresql://" .  # Check for credentials
```

## Source Files

For up-to-date implementation details:
- [eva_common/config.py](../../eva_common/config.py) - Configuration classes
- [.env.example](../../.env.example) - Environment template
- [docker-compose.yml](../../docker-compose.yml) - Service environment
