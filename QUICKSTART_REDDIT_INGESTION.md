# Reddit Ingestion - Quick Start Guide

**TL;DR:** Boring, deterministic Python ingestion that replaces the n8n workflow.

## Quick Test (5 minutes)

```bash
cd /home/koolhand/projects/eva-finance

# 1. Validate the module works (no Docker needed)
python3 test_reddit_ingestion.py

# 2. Start containers (if not already running)
docker-compose up -d

# 3. Wait for containers to be healthy
sleep 10

# 4. Run ingestion with small limit for testing
docker exec eva_worker python3 -m eva_ingest.reddit_posts \
  --subreddits BuyItForLife \
  --limit 5 \
  --debug

# 5. Check results in database
docker exec -it eva_db psql -U eva_user -d eva_db -c \
  "SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE source='reddit') as reddit_posts FROM raw_messages;"
```

**Expected:** You should see 3-5 Reddit posts inserted (some may be filtered out).

## Run with Defaults

```bash
# Fetch 25 posts each from BuyItForLife, Frugal, running
docker exec eva_worker python3 -m eva_ingest.reddit_posts
```

## Run with Makefile

```bash
# Default
make ingest-reddit

# Custom subreddits
make ingest-reddit SUBREDDITS=BuyItForLife,Frugal,coffee LIMIT=50

# Debug mode
make ingest-reddit DEBUG=1

# Check recent posts
make db-query-reddit

# Check processing status
make db-check-status
```

## Schedule with Cron

```bash
# Edit crontab
crontab -e

# Add line (runs every 30 minutes)
0,30 * * * * cd /home/koolhand/projects/eva-finance && docker exec eva_worker python3 -m eva_ingest.reddit_posts >> logs/reddit_ingest.log 2>&1
```

## Verify Everything Works

### 1. Check logs show summary

```
============================================================
Reddit Ingestion Complete
============================================================
Subreddits processed:  3
Posts fetched:         75
Posts filtered out:    22
Posts posted to EVA:   53
Duplicates skipped:    0
Failures:              0
============================================================
```

### 2. Query database

```bash
docker exec -it eva_db psql -U eva_user -d eva_db
```

```sql
-- Recent Reddit posts
SELECT
    id,
    platform_id,
    LEFT(text, 50) as preview,
    meta->>'subreddit' as subreddit,
    created_at
FROM raw_messages
WHERE source = 'reddit'
ORDER BY created_at DESC
LIMIT 10;

-- Count by subreddit
SELECT
    meta->>'subreddit' as subreddit,
    COUNT(*) as count
FROM raw_messages
WHERE source = 'reddit'
GROUP BY meta->>'subreddit'
ORDER BY count DESC;
```

### 3. Test idempotency (run twice)

```bash
# Run once
docker exec eva_worker python3 -m eva_ingest.reddit_posts --limit 5

# Run again - should show all duplicates
docker exec eva_worker python3 -m eva_ingest.reddit_posts --limit 5
```

**Expected:** Second run shows `Duplicates skipped: N` where N is the number of posts from first run.

## Troubleshooting

### Containers not running?
```bash
docker-compose up -d
docker ps --filter "name=eva_"
```

### API not reachable?
```bash
curl http://localhost:9080/health
# Should return: {"status":"ok"}
```

### Module not found?
```bash
# Rebuild worker container
docker-compose build eva-worker
docker-compose up -d eva-worker
```

### Rate limit from Reddit?
Add `--rate-limit-sleep 5` to increase delay between requests.

## Full Documentation

- **Complete Docs:** [docs/ingestion_reddit_posts.md](docs/ingestion_reddit_posts.md)
- **Implementation Summary:** [REDDIT_INGESTION_SUMMARY.md](REDDIT_INGESTION_SUMMARY.md)
- **Source Code:** [eva_ingest/reddit_posts.py](eva_ingest/reddit_posts.py)

## Migration from n8n

1. Test new ingestion (see "Quick Test" above)
2. Verify posts in database
3. Disable n8n workflow at http://localhost:5678
4. Set up cron job (see "Schedule with Cron" above)
5. Monitor for 1 week
6. Delete n8n workflow once stable

## CLI Options Reference

```
--subreddits          Comma-separated list (default: BuyItForLife,Frugal,running)
--limit              Posts per subreddit (default: 25, max: 100)
--eva-api-url        EVA API endpoint (default: http://eva-api:9080/intake/message)
--rate-limit-sleep   Seconds between subreddits (default: 2)
--debug              Enable debug logging
```

## Key Design Points

- **Boring:** Standard library only, no external dependencies
- **Deterministic:** Same inputs = same outputs
- **Idempotent:** Safe to run multiple times (dedup via platform_id)
- **Conservative:** Filters aggressively to avoid noise
- **Auditable:** Clear logs, simple SQL queries
- **Local-first:** No auto-trading, human-gated notifications

---

**Questions?** See [docs/ingestion_reddit_posts.md](docs/ingestion_reddit_posts.md) for complete documentation.
