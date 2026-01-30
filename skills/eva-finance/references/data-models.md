# EVA-Finance Data Models

## Overview

EVA-Finance uses two types of data models:
1. **Pydantic Models** - Request/response validation in FastAPI
2. **PostgreSQL Schema** - Persistent storage with arrays and JSONB

## Pydantic Models (from eva-api/app.py)

### IntakeMessage

The primary model for ingesting raw messages from external sources:

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class IntakeMessage(BaseModel):
    """Raw message intake from external sources (Reddit, n8n, etc.)"""
    source: str                              # e.g., "reddit", "n8n"
    platform_id: Optional[str] = None        # e.g., "reddit_post_abc123"
    timestamp: str                           # ISO8601 timestamp
    text: str                                # Message content
    url: Optional[str] = None                # Source URL
    meta: Dict[str, Any] = Field(default_factory=dict)  # Flexible metadata
```

**Example Usage**:
```json
{
    "source": "reddit",
    "platform_id": "reddit_post_abc123",
    "timestamp": "2026-01-15T10:30:00+00:00",
    "text": "Just switched from Nike to Hoka and never going back!",
    "url": "https://www.reddit.com/r/running/comments/abc123",
    "meta": {
        "subreddit": "running",
        "author": "runner123",
        "reddit_id": "abc123"
    }
}
```

### ProcessedMessage

Extracted/structured data after LLM or fallback processing:

```python
class ProcessedMessage(BaseModel):
    """Processed message with extracted entities and signals"""
    raw_id: int                                     # FK to raw_messages.id
    brand: list[str] = Field(default_factory=list)  # ["Nike", "Hoka"]
    product: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None                  # strong_positive|positive|neutral|negative|strong_negative
    intent: Optional[str] = None                     # buy|own|recommendation|complaint|none
    tickers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)    # ["running", "brand-switch", "comfort"]
```

**Sentiment Values**:
- `strong_positive` - Extremely positive (love, amazing, obsessed)
- `positive` - Generally positive
- `neutral` - No clear sentiment
- `negative` - Generally negative
- `strong_negative` - Extremely negative (hate, awful, terrible)

**Intent Values**:
- `buy` - Intent to purchase
- `own` - Describing ownership/usage
- `recommendation` - Advising others
- `complaint` - Expressing dissatisfaction
- `none` - No clear intent

## Pydantic Settings (from eva_common/config.py)

### DatabaseSettings

```python
from pydantic_settings import BaseSettings
from pydantic import computed_field, model_validator
from typing import Optional

class DatabaseSettings(BaseSettings):
    """Database configuration with flexible env var patterns"""

    # Direct URL takes precedence
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
        """Ensure either database_url or postgres_password is provided"""
        if not self.database_url and not self.postgres_password:
            raise ValueError('Either database_url or postgres_password must be provided')
        return self

    @computed_field
    @property
    def connection_url(self) -> str:
        """Returns database URL (from DATABASE_URL or built from components)"""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
```

### AppSettings

```python
class AppSettings(BaseSettings):
    """Application-level settings (non-database)"""

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
```

## PostgreSQL Schema (from db/init.sql)

### raw_messages

```sql
CREATE TABLE IF NOT EXISTS raw_messages (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    platform_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    text TEXT NOT NULL,
    url TEXT,
    meta JSONB DEFAULT '{}'::jsonb,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_raw_messages_unprocessed
    ON raw_messages(id) WHERE processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_raw_messages_timestamp
    ON raw_messages(timestamp DESC);
```

**Key Points**:
- `meta` uses JSONB for flexible metadata storage
- `processed` flag enables efficient batch queries
- Partial index on `processed = FALSE` for performance

### processed_messages

```sql
CREATE TABLE IF NOT EXISTS processed_messages (
    id SERIAL PRIMARY KEY,
    raw_id INTEGER NOT NULL REFERENCES raw_messages(id) ON DELETE CASCADE,
    brand TEXT[] DEFAULT '{}',
    product TEXT[] DEFAULT '{}',
    category TEXT[] DEFAULT '{}',
    sentiment TEXT,
    intent TEXT,
    tickers TEXT[] DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    processor_version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- GIN indexes for array queries
CREATE INDEX IF NOT EXISTS idx_processed_messages_brand
    ON processed_messages USING GIN(brand);
CREATE INDEX IF NOT EXISTS idx_processed_messages_tags
    ON processed_messages USING GIN(tags);
```

**Key Points**:
- Arrays (`TEXT[]`) for multi-valued fields (brand, tags, etc.)
- GIN indexes for efficient array containment queries
- `processor_version` tracks LLM vs fallback processing

### signal_events

```sql
CREATE TABLE IF NOT EXISTS signal_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    tag TEXT,
    brand TEXT,
    day DATE NOT NULL DEFAULT CURRENT_DATE,
    severity TEXT NOT NULL DEFAULT 'warning',
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    acknowledged BOOLEAN DEFAULT FALSE
);

-- Deduplication index (critical for idempotency)
CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_events_dedup
    ON signal_events(event_type, COALESCE(tag, ''), COALESCE(brand, ''), day);
```

**Event Types**:
- `TAG_ELEVATED` - Tag reached elevated confidence threshold
- `BRAND_DIVERGENCE` - Brand share-of-voice changed significantly
- `RECOMMENDATION_ELIGIBLE` - Signal ready for recommendation
- `WATCHLIST_WARM` - Signal warming up but not yet actionable

### eva_confidence_v1

```sql
CREATE TABLE IF NOT EXISTS eva_confidence_v1 (
    id SERIAL PRIMARY KEY,
    day DATE NOT NULL,
    tag TEXT NOT NULL,
    brand TEXT NOT NULL,
    acceleration_score NUMERIC(5,4),
    intent_score NUMERIC(5,4),
    spread_score NUMERIC(5,4),
    baseline_score NUMERIC(5,4),
    suppression_score NUMERIC(5,4),
    final_confidence NUMERIC(5,4),
    band TEXT,                         -- HIGH|WATCHLIST|SUPPRESSED
    gate_failed_reason TEXT,
    scoring_version TEXT NOT NULL DEFAULT 'v1',
    details JSONB DEFAULT '{}'::jsonb,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(day, tag, brand, scoring_version)
);
```

**Bands**:
- `HIGH` - Ready for recommendation (final_confidence >= 0.60)
- `WATCHLIST` - Warming up (final_confidence >= 0.50)
- `SUPPRESSED` - Below threshold or gated

## Model ↔ Table Mapping

| Pydantic Field | PostgreSQL Column | Notes |
|----------------|-------------------|-------|
| `str` | `TEXT` | Direct mapping |
| `Optional[str]` | `TEXT` (nullable) | NULL allowed |
| `list[str]` | `TEXT[]` | Array type |
| `Dict[str, Any]` | `JSONB` | Flexible JSON |
| `int` | `INTEGER` | Direct mapping |
| `float` | `NUMERIC(5,4)` | 4 decimal precision |
| `datetime` | `TIMESTAMPTZ` | Always with timezone |
| `date` | `DATE` | Date only |
| `bool` | `BOOLEAN` | Direct mapping |

## Validation Patterns

### Range Validation (from CLAUDE.md)

```python
from pydantic import BaseModel, validator

class Signal(BaseModel):
    confidence: float

    @validator('confidence')
    def check_range(cls, v):
        assert 0.0 <= v <= 1.0
        return v
```

### Default Factory for Collections

```python
from pydantic import Field

class ProcessedMessage(BaseModel):
    brand: list[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)
```

**Why `default_factory`**: Avoids mutable default argument issues with `= []`.

## Naming Conventions

| Entity | Python | Database |
|--------|--------|----------|
| Table | `ProcessedMessage` | `processed_messages` |
| Column | `raw_id` | `raw_id` |
| Array | `list[str]` | `TEXT[]` |
| JSON | `Dict[str, Any]` | `JSONB` |
| Timestamp | `datetime` | `TIMESTAMPTZ` |

## Source Files

For up-to-date implementation details:
- [eva-api/app.py](../../eva-api/app.py) - Pydantic models
- [eva_common/config.py](../../eva_common/config.py) - Settings models
- [db/init.sql](../../db/init.sql) - Database schema
- [db/migrations/](../../db/migrations/) - Schema migrations
