# Reddit Ingestion System

**Status:** Production
**Last Updated:** 2026-01-13

## Overview

EVA ingests Reddit posts using a deterministic Python script that runs in a Docker container on a 15-minute loop. This replaced the previous n8n workflow to improve reliability and debuggability.

## Architecture

```
Reddit Public API (JSON)
         ↓
  eva_ingest/reddit_posts.py (rate-limited HTTP)
         ↓
  POST http://eva-api:8080/intake/message
         ↓
  raw_messages table (deduped by platform_id)
```

## How It Works

### 1. Container: eva-ingest-reddit

The `eva-ingest-reddit` service runs continuously via docker-compose:

- **Image:** Reuses `eva-finance-eva-worker` (no separate build needed)
- **Schedule:** Runs every 15 minutes (900 seconds)
- **Subreddits:** BuyItForLife, Frugal, running, malefashionadvice, femalefashionadvice, goodyearwelt, onebag, sneakers
- **Limit:** 25 posts per subreddit per run
- **Idempotency:** Database handles deduplication via `ON CONFLICT (source, platform_id) DO NOTHING`

### 2. Script: eva_ingest/reddit_posts.py

Located at [eva_ingest/reddit_posts.py](../eva_ingest/reddit_posts.py), this script:

- Fetches posts from Reddit's public JSON API
- Filters conservatively (text posts only, minimum 10 characters, no removed/deleted content)
- Posts to EVA API at `http://eva-api:8080/intake/message`
- Uses internal Docker networking (eva-api:8080, not localhost:9080)
- Logs clear statistics (fetched, posted, duplicates, failures)

### 3. Deduplication

Each Reddit post gets a unique `platform_id`:
```
reddit_post_{reddit_id}
```

The database has a unique constraint on `(source, platform_id)`. When a duplicate is posted, the API:
- Skips the insertion (`ON CONFLICT DO NOTHING`)
- Returns `{"status": "received", "duplicate": true}`

This makes ingestion **idempotent** — safe to run repeatedly without creating duplicates.

## Monitoring

### Check Container Status

```bash
docker ps | grep eva-ingest-reddit
```

Expected: Container running, restarting every 15 minutes.

### View Live Logs

```bash
docker logs -f eva-ingest-reddit --tail 50
```

Expected output every 15 minutes:
```
============================================================
Reddit Ingestion Complete
============================================================
Subreddits processed:  8
Posts fetched:         200
Posts filtered out:    78
Posts posted to EVA:   45
Duplicates skipped:    77
Failures:              0
============================================================
2026-01-13T13:45:00+00:00
ingest: sleep 900
```

### Query Database

```bash
docker exec -it eva_db psql -U eva -d eva_finance
```

```sql
-- Recent Reddit posts
SELECT id, platform_id, meta->>'subreddit' as subreddit, processed, created_at
FROM raw_messages
WHERE source = 'reddit'
ORDER BY created_at DESC
LIMIT 10;

-- Posts by subreddit
SELECT meta->>'subreddit' as subreddit, COUNT(*) as count
FROM raw_messages
WHERE source = 'reddit'
GROUP BY meta->>'subreddit'
ORDER BY count DESC;
```

## Configuration

All configuration is in [docker-compose.yml](../docker-compose.yml):

```yaml
environment:
  - EVA_API_URL=http://eva-api:8080/intake/message
  - SUBREDDITS=BuyItForLife,Frugal,running,...
  - LIMIT=25
```

To change subreddits or fetch limits:
1. Edit `docker-compose.yml`
2. Run `docker-compose up -d eva-ingest-reddit`

## Why We Removed n8n

The previous Reddit ingestion used an n8n workflow (`eva_worker/n8n_reddit_ingestion_posts_only.json`). We replaced it because:

1. **Fragile:** n8n workflows are hard to version control and debug
2. **External dependency:** Required a separate n8n instance
3. **Opaque:** Difficult to understand what the workflow was doing
4. **Testing:** Hard to test locally without full n8n setup

The new Python script is:
- **Deterministic:** Same inputs = same outputs
- **Testable:** Can run locally with `--eva-api-url http://localhost:9080/intake/message`
- **Auditable:** One file, clear logging, no hidden state
- **Simple:** Standard library only (urllib, json, logging)

## Important: Do Not Change Unless Broken

This system is **working and stable**. It is designed to be boring and reliable.

**Do not:**
- Add auto-trading
- Add recommendation changes
- Add complex features
- Change scheduling unless Reddit rate-limits us
- Reintroduce n8n

**Only change if:**
- Reddit API changes and ingestion breaks
- Need to add/remove subreddits
- Discovered actual bugs causing data loss

## Troubleshooting

### Container keeps restarting

Check logs:
```bash
docker logs eva-ingest-reddit --tail 100
```

Common issues:
- EVA API not responding (check `docker ps | grep eva-api`)
- Reddit API rate limit (increase sleep time or reduce frequency)

### No new posts appearing

Check:
1. Container is running: `docker ps | grep eva-ingest-reddit`
2. Logs show successful fetches: `docker logs eva-ingest-reddit`
3. Posts are duplicates: Look for "Duplicates skipped" in logs
4. EVA API is healthy: `curl http://localhost:9080/health`

### Posts ingested but not processed

This is a worker issue, not an ingestion issue. Check:
```bash
docker logs eva-worker --tail 100
```

The worker should process `raw_messages` where `processed = FALSE`.

## Manual Run (For Testing)

To manually trigger ingestion without waiting 15 minutes:

```bash
# Inside container
docker exec eva-ingest-reddit python3 -m eva_ingest.reddit_posts --debug

# From host (for local testing)
python3 -m eva_ingest.reddit_posts --eva-api-url http://localhost:9080/intake/message --debug
```

## References

- **Script:** [eva_ingest/reddit_posts.py](../eva_ingest/reddit_posts.py)
- **Detailed docs:** [docs/ingestion_reddit_posts.md](ingestion_reddit_posts.md)
- **Docker config:** [docker-compose.yml](../docker-compose.yml)
- **API endpoint:** [eva-api/app.py](../eva-api/app.py) (`/intake/message`)
- **Database schema:** [db/init.sql](../db/init.sql) (`raw_messages` table)
