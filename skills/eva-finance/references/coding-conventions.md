# EVA-Finance Coding Conventions

## Import Organization

EVA-Finance follows a standard Python import order:

```python
# 1. Standard library
import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from contextlib import contextmanager

# 2. Third-party packages
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from openai import OpenAI

# 3. Local/project imports
from eva_common.db import get_connection
from eva_common.config import app_settings, db_settings
```

## Naming Conventions

### Variables and Functions

```python
# snake_case for variables and functions
def fetch_new_posts(subreddit: str, limit: int = 25) -> List[Dict]:
    rate_limit_sleep = 2.0
    last_request_time = 0.0
    ...

# Constants as UPPER_SNAKE_CASE
DEFAULT_LIMIT = 25
PROCESSOR_LLM = "llm:gpt-4o-mini:v1"
MAX_RETRY_ATTEMPTS = 3
```

### Classes

```python
# PascalCase for classes
class RedditFetcher:
    """Fetches posts from Reddit's public JSON API with rate limiting."""
    pass

class DatabaseSettings(BaseSettings):
    """Database configuration with flexible env var patterns."""
    pass
```

### Database Tables and Columns

```python
# lowercase_with_underscores for SQL
CREATE TABLE raw_messages (
    id SERIAL PRIMARY KEY,
    platform_id TEXT,
    created_at TIMESTAMPTZ
);
```

## Type Hints

EVA-Finance uses type hints throughout:

```python
from typing import Dict, Any, Optional, List, Generator

def brain_extract(raw_id: int, text: str) -> Dict[str, Any]:
    """Extract entities from text using LLM."""
    ...

def get_connection() -> Generator[connection, None, None]:
    """Context manager for database connections."""
    ...

def validate_brand_signal(
    self,
    brand: str,
    timeframe: str = 'today 3-m',
    use_cache: bool = True
) -> Dict:
    """Validate brand signal using Google Trends."""
    ...
```

## Docstring Style

EVA-Finance uses Google-style docstrings:

```python
def fetch_new_posts(self, subreddit: str, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Fetch new posts from a subreddit's public JSON endpoint.

    Args:
        subreddit: Name of subreddit (e.g., "BuyItForLife")
        limit: Number of posts to fetch (max 100 per Reddit API)

    Returns:
        List of post dictionaries from Reddit API

    Raises:
        HTTPError: If Reddit API returns error status
        URLError: If network error occurs
    """
    ...
```

**Class Docstrings**:
```python
class GoogleTrendsValidator:
    """
    Validates brand signals using Google Trends search interest data.

    Methodology:
    1. Fetch 3-month search interest from Google Trends
    2. Calculate recent interest (last 30 days vs full period average)
    3. Detect trend direction (rising/stable/falling)
    4. Apply confidence boost/penalty based on search behavior

    Conservative approach: Prefers false negatives over false positives.
    """
```

## Error Handling

### Standard Pattern

```python
def intake_message(msg: IntakeMessage):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
                conn.commit()
                return {"status": "ok", "id": result[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### With Specific Exception Types

```python
try:
    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
except HTTPError as e:
    logger.error(f"HTTP error fetching r/{subreddit}: {e.code} {e.reason}")
    raise
except URLError as e:
    logger.error(f"Network error fetching r/{subreddit}: {e.reason}")
    raise
except json.JSONDecodeError as e:
    logger.error(f"JSON decode error for r/{subreddit}: {e}")
    raise
```

### Database Integrity Errors

```python
try:
    cur.execute(...)
    conn.commit()
    return True
except psycopg2.IntegrityError:
    # Duplicate entry, skip silently
    return False
except Exception as e:
    logger.error(f"Error inserting post {post['id']}: {e}")
    return False
```

## Logging Patterns

### Setup

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
```

### Usage

```python
# Info for normal operations
logger.info(f"Fetched {len(posts)} posts from r/{subreddit}")
logger.info(f"[EVA-WORKER] Notifications: {stats['sent']} sent, {stats['failed']} failed")

# Warning for recoverable issues
logger.warning(f"No price data available for {ticker}")

# Error for failures
logger.error(f"[EVA-NOTIFY] ✗ Failed to notify draft_id={draft_id}: {e}")

# Debug for verbose output
logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
```

### Logging Prefixes

EVA-Finance uses consistent prefixes for log filtering:

```python
logger.info("[EVA-WORKER] Processing batch...")
logger.info("[EVA-NOTIFY] ✓ Sent notification...")
logger.info("[TRENDS-CACHE] HIT: Nike...")
logger.info("[PAPER-TRADE] ✓ Created paper trade...")
```

## Database Patterns

### Context Manager (Required)

```python
# CORRECT
from eva_common.db import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM raw_messages WHERE id = %s", (id,))
        result = cur.fetchone()
        conn.commit()

# WRONG - Never manage connections manually
conn = psycopg2.connect(...)  # NO!
```

### RealDictCursor for Named Access

```python
from psycopg2.extras import RealDictCursor

with get_connection() as conn:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, brand, tag FROM signal_events")
        rows = cur.fetchall()
        for row in rows:
            print(row["brand"])  # Named access
```

### Parameterized Queries (Always)

```python
# CORRECT - Parameterized
cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))

# WRONG - String interpolation (SQL injection risk)
cur.execute(f"SELECT * FROM users WHERE id = {user_id}")  # NEVER!
```

### Idempotent Writes

```python
# Use ON CONFLICT for idempotent inserts
cur.execute("""
    INSERT INTO signal_events (event_type, tag, brand, day, payload)
    VALUES (%s, %s, %s, %s, %s::jsonb)
    ON CONFLICT DO NOTHING;
""", (event_type, tag, brand, day, json.dumps(payload)))
```

## Comment Style

### Explain WHY, not WHAT

```python
# GOOD - Explains reasoning
# Skip candidates with NULL or empty brand/tag (not actionable for recommendations)
if brand is None or brand == '' or tag is None or tag == '':
    continue

# BAD - States the obvious
# Check if brand is None
if brand is None:
    continue
```

### Section Dividers

```python
# ------------------------------------
# Raw Message Intake Model
# ------------------------------------
class IntakeMessage(BaseModel):
    ...

# ------------------------------------
# Health Check
# ------------------------------------
@app.get("/health")
def health():
    ...
```

### TODO Pattern

```python
# TODO: Add retry logic for transient failures
# NOTE: adjust args to match your signature (seen in generate.py)
```

## Class Structure

```python
class RedditIngestionJob:
    """Main orchestrator for Reddit ingestion job."""

    def __init__(
        self,
        subreddits: List[str],
        limit: int = DEFAULT_LIMIT,
        eva_api_url: str = DEFAULT_EVA_API_URL,
    ):
        # 1. Store parameters
        self.subreddits = subreddits
        self.limit = limit

        # 2. Initialize collaborators
        self.fetcher = RedditFetcher()
        self.api_client = EVAAPIClient(api_url=eva_api_url)

        # 3. Initialize state
        self.stats = {
            "posts_fetched": 0,
            "posts_posted": 0,
        }

    def run(self) -> Dict[str, int]:
        """Main entry point."""
        ...

    def _process_subreddit(self, subreddit: str):
        """Internal helper (prefixed with _)."""
        ...
```

## Test Patterns

```python
# tests/test_google_trends.py
import pytest
from eva_worker.eva_worker.google_trends import GoogleTrendsValidator

def test_validator_initialization():
    """Test that validator initializes without errors."""
    validator = GoogleTrendsValidator()
    assert validator is not None

def test_error_result_structure():
    """Test error result has expected keys."""
    validator = GoogleTrendsValidator()
    result = validator._error_result("Test", "today 3-m", "Test error")
    assert result['validates_signal'] == False
    assert result['confidence_boost'] == 0.0
```

## Source Files

For up-to-date implementation details:
- [eva-api/app.py](../../eva-api/app.py) - API patterns
- [eva_worker/worker.py](../../eva_worker/worker.py) - Worker patterns
- [eva_ingest/reddit_posts.py](../../eva_ingest/reddit_posts.py) - Ingestion patterns
- [eva_worker/eva_worker/google_trends.py](../../eva_worker/eva_worker/google_trends.py) - Validation patterns
- [CLAUDE.md](../../CLAUDE.md) - Code standards
