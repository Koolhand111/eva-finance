---
name: eva-finance
description: Architecture patterns, coding conventions, and integration guide for the EVA-Finance behavioral signal analysis system. Use when (1) Building new EVA modules, (2) Integrating with existing EVA services, (3) Understanding EVA data models and schemas, (4) Following EVA coding standards, (5) Designing features that extend EVA's capabilities
---

# EVA-Finance Architecture Skill

Complete architecture reference for building modules that integrate with EVA-Finance.

## Project Purpose

EVA-Finance is a **Behavioral Signal Engine** that converts conversational data (Reddit posts, social media) into structured financial/behavioral insights. It detects early behavioral trend signals that may indicate brand sentiment shifts, brand switching patterns, and investment opportunities.

**Core Philosophy:**
- Local-first, deterministic, traceable
- Tags represent behaviors, not products
- Brand flow models switching pressure
- Confidence is multi-factor, not binary
- LLM first, heuristics second
- Prefer false negatives over false positives
- Persistence > spike magnitude

## When to Use This Skill

- Building new signal processing modules (e.g., `eva_signals`)
- Adding services to the EVA ecosystem
- Understanding EVA's data flow and models
- Following EVA's coding standards and patterns
- Creating new workers or ingestion pipelines
- Adding API endpoints
- Writing database migrations

## Quick Reference

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.12+ |
| **API Framework** | FastAPI |
| **Database** | PostgreSQL 16 |
| **Data Validation** | Pydantic v2 + pydantic-settings |
| **DB Driver** | psycopg2-binary with ThreadedConnectionPool |
| **Container Orchestration** | Docker Compose |
| **Async Pattern** | FastAPI async endpoints, sync workers |
| **Logging** | Standard logging (structlog recommended) |
| **LLM Integration** | OpenAI API (gpt-4o-mini) |
| **Notifications** | ntfy (self-hosted) |
| **Analytics** | Metabase |

## Key Resources

| File | Description |
|------|-------------|
| [architecture.md](references/architecture.md) | System topology, data flow, service communication patterns |
| [data-models.md](references/data-models.md) | Pydantic models, database schema, validation patterns |
| [coding-conventions.md](references/coding-conventions.md) | Style guide, naming conventions, error handling patterns |
| [config-management.md](references/config-management.md) | Environment variables, Pydantic Settings, config loading |
| [integration-guide.md](references/integration-guide.md) | How to add new services, migrations, and endpoints |

## Examples (Real Code from Codebase)

| File | Description |
|------|-------------|
| [example-pydantic-model.py](examples/example-pydantic-model.py) | IntakeMessage and ProcessedMessage models from eva-api |
| [example-api-endpoint.py](examples/example-api-endpoint.py) | FastAPI endpoint pattern with DB operations |
| [example-worker-loop.py](examples/example-worker-loop.py) | Background worker polling pattern |
| [example-db-query.py](examples/example-db-query.py) | Database query patterns using connection pool |

## Directory Structure

```
eva-finance/
├── eva-api/                  # FastAPI REST service
│   ├── app.py               # Main API endpoints
│   ├── Dockerfile
│   └── requirements.txt
├── eva_worker/               # Background processing
│   ├── worker.py            # Main worker loop
│   ├── scoring.py           # Signal scoring logic
│   ├── eva_confidence_v1.py # Confidence scoring
│   └── eva_worker/          # Submodules
│       ├── notify.py        # Notification polling
│       ├── google_trends.py # Cross-validation
│       └── generate.py      # Recommendation generation
├── eva_common/               # Shared code (CRITICAL)
│   ├── config.py            # Pydantic Settings
│   └── db.py                # Connection pooling
├── eva_ingest/               # Data ingestion
│   └── reddit_posts.py      # Reddit ingestion
├── workers/                  # Isolated workers
│   └── ai-infrastructure/   # AI infra signal worker
├── db/
│   ├── init.sql             # Schema + views
│   └── migrations/          # SQL migrations
├── scripts/
│   └── paper_trading/       # Paper trading scripts
├── docker-compose.yml
├── .env.example
└── CLAUDE.md                # Code standards
```

## Critical Patterns

### 1. Always Use eva_common

```python
# CORRECT - Use centralized config and DB
from eva_common.config import db_settings, app_settings
from eva_common.db import get_connection

# WRONG - Direct psycopg2 or hardcoded config
import psycopg2
conn = psycopg2.connect("postgresql://...")  # NO!
```

### 2. Database Context Managers

```python
# CORRECT - Connection automatically returned to pool
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        conn.commit()

# WRONG - Manual connection management
conn = get_connection()  # This is a context manager, not a connection!
```

### 3. Config via Pydantic Settings

```python
# CORRECT - Type-safe, validated config
from eva_common.config import app_settings
model = app_settings.eva_model  # "gpt-4o-mini"

# WRONG - Direct os.getenv without validation
model = os.getenv("EVA_MODEL", "gpt-4")  # Not validated
```

### 4. Idempotent Operations

All database writes should use `ON CONFLICT` for idempotency:

```python
cur.execute("""
    INSERT INTO signal_events (event_type, tag, brand, day, ...)
    VALUES (%s, %s, %s, %s, ...)
    ON CONFLICT DO NOTHING;  -- Or ON CONFLICT ... DO UPDATE
""", (...))
```

## Pre-Commit Checklist

From CLAUDE.md - run before ANY commit:

```bash
pytest tests/ && black app/ && mypy app/
grep -r "sk-\|postgresql://" .  # Check for credentials
```

## Security Patterns

- Hash user IDs before storage/logging
- Financial amounts as integers (cents, not floats)
- UTC timestamps only
- Never log PII (names, emails, account numbers)
- Never commit credentials (check with grep)

## Source Repository

For up-to-date implementation details:
- GitHub: https://github.com/Koolhand111/eva-finance
- Primary branch: `main`
- Current state: Validated 451 posts over 19 hours
