# EVA-Finance Integration Guide

## Overview

This guide covers how to add new modules, services, and features to EVA-Finance while maintaining consistency with existing patterns.

## Adding a New Service to Docker Compose

### 1. Create Service Directory

```bash
mkdir -p workers/my-new-worker
```

### 2. Create Dockerfile

```dockerfile
# workers/my-new-worker/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install eva_common dependencies first (shared layer)
COPY eva_common/requirements.txt ./eva_common/requirements.txt
RUN pip install --no-cache-dir -r eva_common/requirements.txt

# Install service-specific dependencies
COPY workers/my-new-worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module
COPY eva_common/ ./eva_common/

# Copy service code
COPY workers/my-new-worker/*.py ./

CMD ["python3", "main.py"]
```

### 3. Create requirements.txt

```txt
# workers/my-new-worker/requirements.txt
requests>=2.28.0
# psycopg2-binary and pydantic-settings provided by eva_common
```

### 4. Create Main Script

```python
# workers/my-new-worker/main.py
"""
My New Worker - Description of purpose

Non-goals:
- List what this worker does NOT do
"""

import logging
import time
from eva_common.db import get_connection
from eva_common.config import db_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    logger.info("[MY-WORKER] Starting up...")

    while True:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Your logic here
                    pass
        except Exception as e:
            logger.error(f"[MY-WORKER] Error: {e}")

        time.sleep(60)  # Poll interval


if __name__ == "__main__":
    main()
```

### 5. Add to docker-compose.yml

```yaml
services:
  # ... existing services ...

  my-new-worker:
    build: ./workers/my-new-worker
    container_name: eva_my_new_worker
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - MY_WORKER_ENABLED=true  # Kill switch
    depends_on:
      - db
    networks:
      - eva_net
```

## Adding Database Tables

### 1. Create Migration File

```sql
-- db/migrations/009_add_my_feature_tables.sql
-- Migration: 009_add_my_feature_tables.sql
-- Description: Add tables for my new feature
-- Date: 2026-01-17
-- Safety: Creates new tables only - does NOT modify existing tables

-- Main storage table
CREATE TABLE my_feature_records (
    id SERIAL PRIMARY KEY,
    source VARCHAR NOT NULL,
    data JSONB DEFAULT '{}'::jsonb,
    processed BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Configuration table
CREATE TABLE my_feature_config (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_my_feature_unprocessed
    ON my_feature_records(id) WHERE processed = false;
```

### 2. Run Migration

```bash
# Via Docker
cat db/migrations/009_add_my_feature_tables.sql | \
    docker exec -i eva_db psql -U eva -d eva_finance

# Verify
docker exec -i eva_db psql -U eva -d eva_finance \
    -c "SELECT tablename FROM pg_tables WHERE tablename LIKE 'my_feature%';"
```

### 3. Add to init.sql (for Fresh Installs)

If the tables should exist on fresh installations, add them to `db/init.sql`.

## Adding API Endpoints

### 1. Add to eva-api/app.py

```python
# ------------------------------------
# My New Feature
# ------------------------------------
class MyFeatureRequest(BaseModel):
    """Request model for my feature"""
    name: str
    value: float
    meta: Dict[str, Any] = Field(default_factory=dict)


class MyFeatureResponse(BaseModel):
    """Response model for my feature"""
    id: int
    status: str
    created_at: str


@app.post("/my-feature", response_model=MyFeatureResponse)
def create_my_feature(req: MyFeatureRequest):
    """Create a new my-feature record."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO my_feature_records (source, data)
                    VALUES (%s, %s)
                    RETURNING id, created_at;
                    """,
                    (req.name, Json({"value": req.value, **req.meta}))
                )
                result = cur.fetchone()
                conn.commit()

                return MyFeatureResponse(
                    id=result[0],
                    status="created",
                    created_at=result[1].isoformat()
                )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/my-feature/{feature_id}")
def get_my_feature(feature_id: int):
    """Get a specific my-feature record."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM my_feature_records WHERE id = %s",
                    (feature_id,)
                )
                row = cur.fetchone()

                if not row:
                    raise HTTPException(status_code=404, detail="Not found")

                return dict(row)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 2. Rebuild and Test

```bash
docker compose build eva-api
docker compose up -d eva-api

# Test
curl http://localhost:9080/health
curl -X POST http://localhost:9080/my-feature \
    -H "Content-Type: application/json" \
    -d '{"name": "test", "value": 1.5}'
```

## Adding Worker Tasks

### 1. Create Task Module

```python
# eva_worker/eva_worker/my_task.py
"""
My Task Module

Purpose:
- What this task does
- When it runs

Non-goals:
- What it doesn't do
"""

from __future__ import annotations
import logging
from typing import Dict, Any
from psycopg2.extras import RealDictCursor
from eva_common.db import get_connection

logger = logging.getLogger(__name__)


def process_my_task() -> Dict[str, int]:
    """
    Process pending my-task records.

    Returns:
        Dict with 'processed' and 'failed' counts
    """
    stats = {"processed": 0, "failed": 0}

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Fetch pending records (atomic claim)
                cur.execute("""
                    SELECT id, source, data
                    FROM my_feature_records
                    WHERE processed = false
                    ORDER BY created_at ASC
                    LIMIT 10
                    FOR UPDATE SKIP LOCKED
                """)

                pending = cur.fetchall()

                if not pending:
                    return stats

                logger.info(f"[MY-TASK] Found {len(pending)} pending records")

                for record in pending:
                    try:
                        # Process record
                        _process_record(record)

                        # Mark as processed
                        cur.execute(
                            "UPDATE my_feature_records SET processed = true WHERE id = %s",
                            (record["id"],)
                        )
                        stats["processed"] += 1

                    except Exception as e:
                        logger.error(f"[MY-TASK] Failed record {record['id']}: {e}")
                        stats["failed"] += 1

                conn.commit()

    except Exception as e:
        logger.error(f"[MY-TASK] Fatal error: {e}")

    return stats


def _process_record(record: Dict[str, Any]) -> None:
    """Process a single record."""
    # Your processing logic here
    pass
```

### 2. Integrate into Worker Loop

```python
# eva_worker/worker.py

# Import the new task
try:
    from eva_worker.eva_worker.my_task import process_my_task
except ImportError:
    logger.warning("Could not import process_my_task - my task disabled")
    process_my_task = None


def main():
    last_my_task_run = 0
    MY_TASK_INTERVAL = 300  # Every 5 minutes

    while True:
        # Existing processing...
        n = process_batch(limit=20)
        emit_trigger_events()

        # Run my task periodically
        current_time = time.time()
        if process_my_task and (current_time - last_my_task_run) >= MY_TASK_INTERVAL:
            try:
                stats = process_my_task()
                if stats["processed"] > 0:
                    logger.info(f"[MY-TASK] Processed {stats['processed']} records")
            except Exception as e:
                logger.error(f"[MY-TASK] Error: {e}")
            finally:
                last_my_task_run = current_time

        time.sleep(10)
```

## Sharing Code Between Services

### Use eva_common Package

All shared code goes in `eva_common/`:

```python
# eva_common/__init__.py
from .config import db_settings, app_settings, settings
from .db import get_connection, get_pool, close_pool

__all__ = [
    'db_settings',
    'app_settings',
    'settings',
    'get_connection',
    'get_pool',
    'close_pool',
]
```

### Adding New Shared Code

```python
# eva_common/utils.py
"""Shared utility functions"""

import hashlib
from datetime import datetime, timezone


def hash_user_id(user_id: str) -> str:
    """Hash user ID for privacy (per CLAUDE.md)"""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def utc_now() -> datetime:
    """Get current UTC datetime"""
    return datetime.now(timezone.utc)
```

### Update eva_common/requirements.txt

```txt
# EVA Common shared dependencies
pydantic>=2.0.0
pydantic-settings>=2.0.0
psycopg2-binary>=2.9.0
# Add new dependencies here
```

## PR Checklist for New Features

### Before Submitting

- [ ] **Code follows conventions** (see coding-conventions.md)
- [ ] **Uses eva_common** for config and DB access
- [ ] **Type hints** on all functions
- [ ] **Docstrings** on public functions/classes
- [ ] **Logging** uses consistent prefixes (`[MY-FEATURE]`)
- [ ] **Error handling** with appropriate exception types
- [ ] **Idempotent** database operations (ON CONFLICT)

### Database Changes

- [ ] Migration file in `db/migrations/`
- [ ] Migration tested on fresh database
- [ ] Indexes added for common queries
- [ ] No destructive changes to existing tables

### Docker Changes

- [ ] Dockerfile follows existing pattern
- [ ] Service added to docker-compose.yml
- [ ] Environment variables documented
- [ ] Kill switch for new workers

### Security

- [ ] No credentials in code
- [ ] Run credential check: `grep -r "sk-\|postgresql://" .`
- [ ] User IDs hashed before logging/storage
- [ ] No PII in logs

### Testing

- [ ] `pytest tests/` passes
- [ ] `black app/` formatting applied
- [ ] `mypy app/` type checking passes
- [ ] Manual testing with Docker Compose

## Common Pitfalls

### 1. Direct Database Connections

```python
# WRONG
import psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"])

# CORRECT
from eva_common.db import get_connection
with get_connection() as conn:
    ...
```

### 2. Hardcoded Config

```python
# WRONG
MODEL = "gpt-4o-mini"
NTFY_URL = "http://eva_ntfy:80"

# CORRECT
from eva_common.config import app_settings
MODEL = app_settings.eva_model
NTFY_URL = app_settings.ntfy_url
```

### 3. Non-Idempotent Writes

```python
# WRONG - Creates duplicates
cur.execute("INSERT INTO signal_events (...) VALUES (...)")

# CORRECT - Idempotent
cur.execute("""
    INSERT INTO signal_events (...)
    VALUES (...)
    ON CONFLICT DO NOTHING
""")
```

### 4. Missing Logging Prefix

```python
# WRONG
logger.info("Processing started")

# CORRECT
logger.info("[MY-WORKER] Processing started")
```

## Source Files

For up-to-date implementation details:
- [docker-compose.yml](../../docker-compose.yml)
- [eva_common/](../../eva_common/)
- [eva-api/app.py](../../eva-api/app.py)
- [eva_worker/worker.py](../../eva_worker/worker.py)
- [db/migrations/](../../db/migrations/)
- [workers/ai-infrastructure/](../../workers/ai-infrastructure/) - Example isolated worker
