# Reddit Post Ingestion

Deterministic Python ingestion job that fetches text posts from Reddit and posts them to EVA-Finance for processing.

## Overview

The Reddit ingestion job replaces the fragile n8n workflow with a boring, testable Python script that:

- Fetches new text posts from configured subreddits via Reddit's public JSON API
- Filters conservatively (only real text posts, no removed/deleted content)
- Posts to EVA API's `/intake/message` endpoint
- Handles deduplication via `platform_id` (EVA API's ON CONFLICT clause)
- Respects rate limits with configurable sleep between requests
- Logs all operations clearly for auditing

**Design Philosophy:**
- Local-first, human-gated (no auto-trading)
- Boring and deterministic (no surprises)
- Conservative filtering (favor false negatives over false positives)
- Idempotent and safe to run on a schedule

## Architecture

```
Reddit Public API (JSON)
         ↓
  RedditFetcher (rate-limited HTTP)
         ↓
  RedditPostProcessor (filter + normalize)
         ↓
  EVAAPIClient → POST /intake/message
         ↓
  raw_messages table (deduped by source + platform_id)
```

## Usage

### Basic Usage

```bash
# Run with default subreddits (BuyItForLife, Frugal, running)
python -m eva_ingest.reddit_posts

# Custom subreddits
python -m eva_ingest.reddit_posts --subreddits BuyItForLife,Frugal,running,coffee

# Fetch more posts per subreddit
python -m eva_ingest.reddit_posts --limit 50

# Custom EVA API URL (for testing outside docker network)
python -m eva_ingest.reddit_posts --eva-api-url http://localhost:9080/intake/message

# Enable debug logging
python -m eva_ingest.reddit_posts --debug
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--subreddits` | `BuyItForLife,Frugal,running` | Comma-separated list of subreddits |
| `--limit` | `25` | Number of posts to fetch per subreddit (max 100) |
| `--eva-api-url` | `http://eva-api:9080/intake/message` | EVA API endpoint URL (also reads `$EVA_API_URL`) |
| `--rate-limit-sleep` | `2` | Seconds to sleep between subreddit fetches |
| `--debug` | `false` | Enable debug logging |

## Running in Docker

### Option 1: Inside eva-worker Container

```bash
# Run ingestion inside the existing eva-worker container
docker exec eva-finance-eva-worker-1 python -m eva_ingest.reddit_posts

# Or with custom options
docker exec eva-finance-eva-worker-1 python -m eva_ingest.reddit_posts --limit 50 --debug
```

This works because the `eva-worker` container is on the `eva_net` Docker network and can reach `eva-api:9080`.

### Option 2: From Host Machine

If running from your local machine (outside Docker), you need to use `localhost:9080` instead of `eva-api:9080`:

```bash
# From host machine
python -m eva_ingest.reddit_posts --eva-api-url http://localhost:9080/intake/message
```

**Important:** The EVA API container must have port 9080 exposed on localhost for this to work. Check your `docker-compose.yml`.

### Option 3: Dedicated Ingestion Container (Future)

You can also create a dedicated ingestion container by adding a service to `docker-compose.yml`:

```yaml
services:
  eva-ingest:
    build:
      context: .
      dockerfile: Dockerfile.ingest
    depends_on:
      - eva-api
    networks:
      - eva_net
    environment:
      - EVA_API_URL=http://eva-api:9080/intake/message
    volumes:
      - ./eva_ingest:/app/eva_ingest
    command: python -m eva_ingest.reddit_posts
```

## Scheduling Ingestion

### Option 1: Cron (Recommended)

Run ingestion every 30 minutes using cron:

```bash
# Edit crontab
crontab -e

# Add this line (runs at :00 and :30 of every hour)
0,30 * * * * cd /home/koolhand/projects/eva-finance && docker exec eva-finance-eva-worker-1 python -m eva_ingest.reddit_posts >> logs/reddit_ingest.log 2>&1
```

**Log rotation:** Use `logrotate` to prevent log files from growing indefinitely:

```bash
# /etc/logrotate.d/eva-ingest
/home/koolhand/projects/eva-finance/logs/reddit_ingest.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

### Option 2: Systemd Timer

Create a systemd service and timer:

**File: `/etc/systemd/system/eva-reddit-ingest.service`**
```ini
[Unit]
Description=EVA Reddit Ingestion
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=/home/koolhand/projects/eva-finance
ExecStart=/usr/bin/docker exec eva-finance-eva-worker-1 python -m eva_ingest.reddit_posts
StandardOutput=append:/var/log/eva-reddit-ingest.log
StandardError=append:/var/log/eva-reddit-ingest.log
User=koolhand

[Install]
WantedBy=multi-user.target
```

**File: `/etc/systemd/system/eva-reddit-ingest.timer`**
```ini
[Unit]
Description=Run EVA Reddit Ingestion every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable eva-reddit-ingest.timer
sudo systemctl start eva-reddit-ingest.timer

# Check status
sudo systemctl status eva-reddit-ingest.timer
sudo systemctl list-timers eva-reddit-ingest.timer
```

### Option 3: Makefile Target

Use the provided Makefile target for one-off runs:

```bash
# Run ingestion now
make ingest-reddit

# Or with custom subreddits
make ingest-reddit SUBREDDITS=BuyItForLife,Frugal
```

## Verification

### 1. Check Logs

The ingestion job logs a clear summary:

```
2026-01-13 10:30:00 [INFO] Starting Reddit ingestion for 3 subreddits
2026-01-13 10:30:00 [INFO] Subreddits: BuyItForLife, Frugal, running
2026-01-13 10:30:00 [INFO] Processing r/BuyItForLife...
2026-01-13 10:30:01 [INFO] Fetched 25 posts from r/BuyItForLife
2026-01-13 10:30:01 [INFO] r/BuyItForLife: 18 valid text posts (7 filtered out)
...
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

### 2. Query Database

Check that posts were inserted into `raw_messages`:

```bash
# Connect to database
docker exec -it eva-finance-db-1 psql -U eva_user -d eva_db

# Query recent Reddit posts
SELECT
    id,
    source,
    platform_id,
    timestamp,
    LENGTH(text) as text_length,
    meta->>'subreddit' as subreddit,
    processed,
    created_at
FROM raw_messages
WHERE source = 'reddit'
ORDER BY created_at DESC
LIMIT 10;

# Count posts by subreddit
SELECT
    meta->>'subreddit' as subreddit,
    COUNT(*) as post_count,
    MAX(timestamp) as latest_post
FROM raw_messages
WHERE source = 'reddit'
GROUP BY meta->>'subreddit'
ORDER BY post_count DESC;

# Check for duplicates (should be none)
SELECT platform_id, COUNT(*) as count
FROM raw_messages
WHERE source = 'reddit'
GROUP BY platform_id
HAVING COUNT(*) > 1;
```

### 3. Check Processing Status

Verify that posts are being processed by the worker:

```sql
-- Check processing progress
SELECT
    COUNT(*) FILTER (WHERE processed = TRUE) as processed_count,
    COUNT(*) FILTER (WHERE processed = FALSE) as unprocessed_count,
    COUNT(*) as total_count
FROM raw_messages
WHERE source = 'reddit';

-- View processed message details
SELECT
    pm.id,
    rm.platform_id,
    rm.meta->>'subreddit' as subreddit,
    pm.brand,
    pm.tags,
    pm.sentiment,
    pm.intent
FROM processed_messages pm
JOIN raw_messages rm ON rm.id = pm.raw_id
WHERE rm.source = 'reddit'
ORDER BY pm.created_at DESC
LIMIT 10;
```

## Filtering Logic

The ingestion job applies conservative filtering to favor **false negatives over false positives**:

### ✅ Included Posts
- Text posts with `selftext` content
- Minimum length: 10 characters
- Real content (not removed/deleted)

### ❌ Filtered Out
- Link posts (no selftext)
- Empty selftext
- Posts with `[removed]` or `[deleted]` content
- Very short posts (< 10 chars)

**Rationale:** It's better to miss a few marginal posts than to ingest noise that pollutes the signal extraction pipeline.

## Deduplication Strategy

Deduplication is handled by the **EVA API** using the `ON CONFLICT (source, platform_id) DO NOTHING` clause.

- Each post gets a unique `platform_id`: `reddit_post_{reddit_id}`
- The database has a unique constraint on `(source, platform_id)`
- If a post is already in the database, the INSERT is silently skipped
- The API returns `{"status": "received", "duplicate": true}`

**This makes the ingestion job idempotent** — you can run it multiple times without creating duplicates.

### Local State (Not Used)

We deliberately **do NOT** maintain local state files (e.g., `.last_ingested.json`) because:

1. The database is the source of truth
2. Local state introduces complexity and failure modes
3. The API's ON CONFLICT clause is simpler and more reliable
4. We want to keep the ingestion job stateless

## Rate Limiting

Reddit's public JSON API has rate limits (approximately 60 requests/minute for unauthenticated clients).

**Our approach:**
- Default sleep: 2 seconds between subreddit fetches
- User-Agent header: `EVA-Finance/1.0 (Reddit text post ingestion; boring and deterministic)`
- Configurable via `--rate-limit-sleep` flag

**Best practices:**
- Don't fetch more often than every 15 minutes
- Keep `--limit` reasonable (25-50 posts per subreddit)
- Monitor for HTTP 429 (Too Many Requests) errors in logs

## Troubleshooting

### Error: "Connection refused" to eva-api:9080

**Cause:** Running from host machine, but using Docker hostname `eva-api`.

**Fix:** Use `--eva-api-url http://localhost:9080/intake/message` or set `EVA_API_URL` environment variable.

### Error: HTTP 429 (Too Many Requests) from Reddit

**Cause:** Rate limit exceeded.

**Fix:** Increase `--rate-limit-sleep` to 3-5 seconds, or reduce ingestion frequency.

### Ingestion runs but posts don't appear in database

**Cause:** Check for HTTP errors in logs.

**Debug steps:**
1. Check logs for HTTP errors: `docker logs eva-finance-eva-api-1`
2. Verify EVA API is running: `curl http://localhost:9080/health`
3. Check database connection: `docker exec eva-finance-db-1 psql -U eva_user -d eva_db -c "\dt"`

### Posts ingested but not processed

**Cause:** Worker is not running or has errors.

**Fix:**
1. Check worker status: `docker ps | grep eva-worker`
2. Check worker logs: `docker logs eva-finance-eva-worker-1`
3. Restart worker: `docker restart eva-finance-eva-worker-1`

## Migration from n8n

If you're currently using the n8n workflow:

1. **Test the new ingestion:**
   ```bash
   python -m eva_ingest.reddit_posts --debug
   ```

2. **Verify posts in database** (see Verification section above)

3. **Disable n8n workflow:**
   - Open n8n at http://localhost:5678
   - Find "EVA Reddit Ingestion - Posts Only" workflow
   - Set it to "Inactive" (do NOT delete yet)

4. **Set up scheduled ingestion** (cron or systemd timer)

5. **Monitor for 1 week** to ensure everything works

6. **Optional: Delete n8n workflow** after confirming stability

## Future Enhancements

Potential improvements (not in v1):

- [ ] Support for Reddit API authentication (OAuth) for higher rate limits
- [ ] Configurable filtering rules (min length, keyword filters)
- [ ] Multiple source support (Twitter, RSS feeds, etc.)
- [ ] Dry-run mode (fetch and log, but don't post)
- [ ] Metrics export (Prometheus, StatsD)
- [ ] Checkpoint state file for resuming after failures
- [ ] Parallel subreddit fetching (async/await)

## References

- EVA API Schema: [eva-api/app.py](../eva-api/app.py) (IntakeMessage model)
- Database Schema: [db/init.sql](../db/init.sql) (raw_messages table)
- Reddit JSON API: https://www.reddit.com/dev/api/
- n8n Workflow (deprecated): [eva_worker/n8n_reddit_ingestion_posts_only.json](../eva_worker/n8n_reddit_ingestion_posts_only.json)
