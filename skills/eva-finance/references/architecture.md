# EVA-Finance Architecture

## System Overview

EVA-Finance is a behavioral signal engine that processes conversational data into actionable financial insights. The system follows a pipeline architecture:

```
Data Sources → Ingestion → Processing → Signal Detection → Notification
     ↓             ↓            ↓              ↓              ↓
  Reddit      eva_ingest    eva_worker    Confidence      ntfy/n8n
  n8n         eva-api      LLM Extract    Scoring
```

## Service Topology

### Docker Compose Stack

**Location**: `~/projects/eva-finance/docker-compose.yml`
**Network**: `eva_net` (bridge driver)

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| `db` | eva_db | 5432 (internal) | PostgreSQL 16 database |
| `eva-api` | eva_api | 9080:8080 | FastAPI ingestion endpoint |
| `eva-worker` | eva_worker | - | Background signal processing |
| `metabase` | eva_metabase | 3000 | Analytics dashboard |
| `ntfy` | eva_ntfy | 8085:80 | Push notifications |
| `eva-ingest-reddit` | eva-finance-eva-ingest-reddit-1 | - | Reddit post ingestion loop |
| `eva-ai-infrastructure-worker` | eva_ai_infra_worker | - | AI infrastructure signal collection |

### Service Definitions (from docker-compose.yml)

```yaml
services:
  db:
    image: postgres:16
    container_name: eva_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - eva_db_data:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - eva_net

  eva-api:
    build:
      context: .
      dockerfile: eva-api/Dockerfile
    container_name: eva_api
    restart: unless-stopped
    environment:
      DATABASE_URL: ${DATABASE_URL}
    depends_on:
      - db
    ports:
      - "9080:8080"
    networks:
      - eva_net
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()"]
      interval: 30s
      timeout: 5s
      retries: 3

  eva-worker:
    build:
      context: .
      dockerfile: eva_worker/Dockerfile
    container_name: eva_worker
    restart: unless-stopped
    env_file:
      - .env
    environment:
      NOTIFICATION_POLL_INTERVAL: 60
      NTFY_URL: http://eva_ntfy:80
    depends_on:
      - db
    networks:
      - eva_net
    volumes:
      - ./scripts:/app/scripts:ro
```

## Data Flow Diagram

```
                                    ┌──────────────────┐
                                    │   Reddit API     │
                                    │ (public JSON)    │
                                    └────────┬─────────┘
                                             │
                                             ▼
┌─────────────┐                    ┌──────────────────┐
│   n8n       │ ─── HTTP POST ───▶ │   eva-api        │
│ (external)  │                    │ :9080            │
└─────────────┘                    │ /intake/message  │
                                   └────────┬─────────┘
         ┌──────────────────────────────────┼────────────────────────────┐
         │                                  │                            │
         ▼                                  ▼                            ▼
┌──────────────────┐              ┌──────────────────┐          ┌──────────────────┐
│ raw_messages     │              │ processed_msgs   │          │ signal_events    │
│ (unprocessed)    │              │ (LLM extracted)  │          │ (triggers)       │
└────────┬─────────┘              └──────────────────┘          └────────┬─────────┘
         │                                                               │
         │ SELECT WHERE processed=FALSE                                  │
         ▼                                                               │
┌──────────────────┐                                                     │
│   eva-worker     │ ─────────────────────────────────────────────────────
│ (polling loop)   │
│                  │ ◄─── brain_extract() ───▶ OpenAI API
│                  │ ◄─── emit_trigger_events()
│                  │ ◄─── poll_and_notify()
└────────┬─────────┘
         │
         │ ntfy POST
         ▼
┌──────────────────┐
│   ntfy           │ ──▶ Mobile/Desktop notifications
│   :8085          │
└──────────────────┘
```

## Service Communication Patterns

### 1. REST API (Synchronous)

External services communicate with eva-api via HTTP POST:

```
n8n ──POST──▶ http://10.10.0.210:9080/intake/message
eva-ingest ──POST──▶ http://eva-api:8080/intake/message
```

**Note**: n8n uses host IP (10.10.0.210) because it runs in a separate Docker network.

### 2. Shared Database (Primary Pattern)

Services communicate through the PostgreSQL database:

```
eva-api ──INSERT──▶ raw_messages
eva-worker ──SELECT──▶ raw_messages (WHERE processed=FALSE)
eva-worker ──INSERT──▶ processed_messages
eva-worker ──INSERT──▶ signal_events
```

### 3. Database Views for Signal Detection

SQL views compute derived signals without service coupling:

- `v_trigger_tag_elevated` - Tags in ELEVATED state
- `v_trigger_brand_divergence` - Brands with share-of-voice changes
- `v_eva_candidate_brand_signals_v1` - Candidates for confidence scoring
- `v_brand_tag_daily_summary` - Daily metrics per brand+tag

## Database Connection Pooling

EVA uses `psycopg2.pool.ThreadedConnectionPool` via `eva_common.db`:

```python
# From eva_common/db.py
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None

def _create_pool() -> ThreadedConnectionPool:
    return ThreadedConnectionPool(
        minconn=db_settings.db_pool_min,  # Default: 2
        maxconn=db_settings.db_pool_max,  # Default: 10
        dsn=db_settings.connection_url,
    )

@contextmanager
def get_connection() -> Generator[connection, None, None]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)  # Return to pool
```

**Usage**:
```python
from eva_common.db import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        conn.commit()
# Connection automatically returned to pool
```

## Database Tables

### Core Tables

| Table | Purpose |
|-------|---------|
| `raw_messages` | Incoming messages from external sources |
| `processed_messages` | LLM-extracted structured data |
| `signal_events` | Emitted signal events (triggers, recommendations) |
| `behavior_states` | Tag state tracking (ELEVATED, NORMAL) |
| `eva_confidence_v1` | Computed confidence scores |
| `recommendation_drafts` | Draft recommendations awaiting approval |
| `paper_trades` | Paper trading positions for validation |
| `google_trends_validation` | Google Trends cross-validation results |
| `brand_ticker_mapping` | Brand to stock ticker mapping |

### AI Infrastructure Tables (Isolated)

| Table | Purpose |
|-------|---------|
| `ai_infrastructure_raw_posts` | Raw Reddit posts from AI infra subreddits |
| `ai_infrastructure_subreddits` | Subreddit configuration |

## Startup Dependencies

```
db (postgres:16)
    ↓
eva-api (depends_on: db)
    ↓
eva-worker (depends_on: db)
    ↓
eva-ingest-reddit (depends_on: eva-api)
    ↓
eva-ai-infrastructure-worker (depends_on: db)
```

## Port Map

| Port | Service | Access | Notes |
|------|---------|--------|-------|
| 9080 | eva_api | 0.0.0.0 | **Primary ingestion endpoint** |
| 5432 | eva_db | internal | Database (not exposed) |
| 3000 | eva_metabase | 0.0.0.0 | Analytics dashboard |
| 8085 | eva_ntfy | 0.0.0.0 | Notifications |

## Worker Execution Model

### eva-worker (Main Worker)

Continuous polling loop with 10-second intervals:

```python
def main():
    while True:
        n = process_batch(limit=20)  # Process raw messages
        emit_trigger_events()         # Check trigger views

        if poll_and_notify:           # Every 60 seconds
            poll_and_notify()         # Send notifications

        time.sleep(10)
```

### eva-ingest-reddit

Shell loop with 15-minute intervals:

```bash
while true; do
    python3 -m eva_ingest.reddit_posts --subreddits "$SUBREDDITS" --limit "$LIMIT"
    sleep 900
done
```

### eva-ai-infrastructure-worker

Similar polling pattern with configurable interval.

## Source Files

For up-to-date implementation details:
- [docker-compose.yml](../../docker-compose.yml)
- [eva-api/app.py](../../eva-api/app.py)
- [eva_worker/worker.py](../../eva_worker/worker.py)
- [eva_common/db.py](../../eva_common/db.py)
- [db/init.sql](../../db/init.sql)
- [docs/EVA_STACK_TOPOLOGY.md](../../docs/EVA_STACK_TOPOLOGY.md)
