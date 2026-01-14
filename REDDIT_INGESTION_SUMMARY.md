# Reddit Ingestion v1 - Implementation Summary

**Date:** 2026-01-13
**Status:** ✅ Complete and ready for testing

---

## What Was Built

A deterministic, testable Python ingestion job that replaces the fragile n8n Reddit workflow with a boring, auditable local-first solution.

### Core Module: `eva_ingest/reddit_posts.py`

**Location:** `/home/koolhand/projects/eva-finance/eva_ingest/reddit_posts.py`

**Key Features:**
- ✅ Fetches text posts from Reddit's public JSON API
- ✅ Conservative filtering (only real text posts, no removed/deleted content)
- ✅ Rate-limited HTTP requests (2 second sleep between subreddits)
- ✅ Posts to EVA API at `http://eva-api:9080/intake/message`
- ✅ Idempotent via `platform_id` deduplication (handled by EVA API's ON CONFLICT)
- ✅ Clear logging with statistics summary
- ✅ CLI with argument parsing
- ✅ Zero external dependencies (uses stdlib only: `urllib`, `json`, `argparse`, `logging`)

**Architecture:**
```
RedditFetcher (HTTP client with rate limiting)
    ↓
RedditPostProcessor (filter + normalize)
    ↓
EVAAPIClient (POST to /intake/message)
    ↓
raw_messages table (deduped by source + platform_id)
```

**Normalized Message Format:**
```json
{
  "source": "reddit",
  "platform_id": "reddit_post_{id}",
  "timestamp": "2026-01-13T10:30:00+00:00",
  "text": "{title}\n\n{selftext}",
  "url": "https://www.reddit.com/r/.../...",
  "meta": {
    "subreddit": "BuyItForLife",
    "author": "username",
    "reddit_id": "abc123"
  }
}
```

---

## Files Created

| File | Purpose |
|------|---------|
| `eva_ingest/__init__.py` | Package init |
| `eva_ingest/reddit_posts.py` | Main ingestion script (454 lines) |
| `docs/ingestion_reddit_posts.md` | Complete documentation with usage, scheduling, troubleshooting |
| `Makefile` | Convenience targets for running ingestion and querying database |
| `REDDIT_INGESTION_SUMMARY.md` | This file (implementation summary) |

---

## Files Modified

| File | Change |
|------|--------|
| `eva_worker/n8n_reddit_ingestion_posts_only.json` | Added deprecation notice to workflow name and notes field |
| `eva_worker/eva_ingest/` | Copied module into worker for Docker build |

---

## Usage Examples

### 1. Run from Docker Container (Recommended)

```bash
# Default subreddits (BuyItForLife, Frugal, running), 25 posts each
docker exec eva_worker python3 -m eva_ingest.reddit_posts

# Custom subreddits
docker exec eva_worker python3 -m eva_ingest.reddit_posts \
  --subreddits BuyItForLife,Frugal,running,coffee \
  --limit 50

# Enable debug logging
docker exec eva_worker python3 -m eva_ingest.reddit_posts --debug
```

### 2. Run via Makefile

```bash
# Default settings
make ingest-reddit

# Custom settings
make ingest-reddit SUBREDDITS=BuyItForLife,Frugal LIMIT=50 DEBUG=1
```

### 3. Run from Host (for local testing)

```bash
# Note: Uses localhost:9080 instead of eva-api:9080
python -m eva_ingest.reddit_posts \
  --eva-api-url http://localhost:9080/intake/message
```

---

## How to Test End-to-End

### Step 1: Start Docker Containers

```bash
cd /home/koolhand/projects/eva-finance
docker-compose up -d

# Verify containers are running
make check-containers

# Check EVA API health
make check-health
```

**Expected output:**
```
NAMES          STATUS                   PORTS
eva_db         Up 2 minutes            5432/tcp
eva_api        Up 2 minutes (healthy)  0.0.0.0:9080->8080/tcp
eva_worker     Up 2 minutes
eva_metabase   Up 2 minutes            0.0.0.0:3000->3000/tcp
eva_ntfy       Up 2 minutes            0.0.0.0:8085->80/tcp
```

### Step 2: Run Ingestion

```bash
# Run with a small limit for initial test
docker exec eva_worker python3 -m eva_ingest.reddit_posts \
  --subreddits BuyItForLife \
  --limit 5 \
  --debug
```

**Expected log output:**
```
2026-01-13 13:30:00 [INFO] Starting Reddit ingestion for 1 subreddits
2026-01-13 13:30:00 [INFO] Subreddits: BuyItForLife
2026-01-13 13:30:00 [INFO] Limit per subreddit: 5
2026-01-13 13:30:00 [INFO] EVA API: http://eva-api:9080/intake/message
2026-01-13 13:30:00 [INFO] Processing r/BuyItForLife...
2026-01-13 13:30:01 [INFO] Fetched 5 posts from r/BuyItForLife
2026-01-13 13:30:01 [INFO] r/BuyItForLife: 3 valid text posts (2 filtered out)
============================================================
Reddit Ingestion Complete
============================================================
Subreddits processed:  1
Posts fetched:         5
Posts filtered out:    2
Posts posted to EVA:   3
Duplicates skipped:    0
Failures:              0
============================================================
```

### Step 3: Verify in Database

```bash
# Query recent Reddit posts
make db-query-reddit

# Or directly via psql
docker exec -it eva_db psql -U eva_user -d eva_db

# Then run SQL:
SELECT
    id,
    source,
    platform_id,
    LEFT(text, 50) as text_preview,
    meta->>'subreddit' as subreddit,
    created_at
FROM raw_messages
WHERE source = 'reddit'
ORDER BY created_at DESC
LIMIT 10;
```

**Expected output:**
```
 id | source |     platform_id      |                  text_preview                  | subreddit    |         created_at
----+--------+----------------------+------------------------------------------------+--------------+----------------------------
  1 | reddit | reddit_post_abc123   | Best running shoes for wide feet\n\nI've been...| running      | 2026-01-13 13:30:01.123456
  2 | reddit | reddit_post_def456   | My favorite buy it for life items\n\nHere's... | BuyItForLife | 2026-01-13 13:30:01.234567
...
```

### Step 4: Check for Duplicates (Idempotency Test)

```bash
# Run ingestion again with same parameters
docker exec eva_worker python3 -m eva_ingest.reddit_posts \
  --subreddits BuyItForLife \
  --limit 5
```

**Expected:**
```
Posts posted to EVA:   0
Duplicates skipped:    3   # <-- All posts were duplicates
Failures:              0
```

### Step 5: Check Processing Status

```bash
make db-check-status
```

**Expected output:**
```
 processed | unprocessed | total
-----------+-------------+-------
         0 |           3 |     3
```

The worker should eventually process these messages and set `processed = TRUE`.

---

## Scheduling (Production)

### Option 1: Cron (Recommended)

Add to crontab (`crontab -e`):

```cron
# Run Reddit ingestion every 30 minutes
0,30 * * * * cd /home/koolhand/projects/eva-finance && docker exec eva_worker python3 -m eva_ingest.reddit_posts >> logs/reddit_ingest.log 2>&1
```

### Option 2: Systemd Timer

See [docs/ingestion_reddit_posts.md](docs/ingestion_reddit_posts.md) for full systemd timer setup.

---

## Validation Checklist

Before considering this done, verify:

- [x] Module created: `eva_ingest/reddit_posts.py`
- [x] Documentation created: `docs/ingestion_reddit_posts.md`
- [x] Makefile targets added: `ingest-reddit`, `db-query-reddit`, `db-check-status`
- [x] n8n workflow marked deprecated
- [x] Module copied into `eva_worker/` for Docker build
- [ ] **TODO:** Start containers and run end-to-end test
- [ ] **TODO:** Verify posts in database
- [ ] **TODO:** Test idempotency (run twice, check for duplicates)
- [ ] **TODO:** Set up scheduling (cron or systemd)

---

## Migration from n8n

1. **Test the new ingestion** (see Step 2 above)
2. **Verify posts in database** (see Step 3 above)
3. **Disable n8n workflow:**
   - Open http://localhost:5678
   - Find "EVA Reddit Ingestion - Posts Only [DEPRECATED]"
   - Set to "Inactive" (do NOT delete yet)
4. **Set up scheduled ingestion** (cron or systemd)
5. **Monitor for 1 week** to ensure stability
6. **Optional: Delete n8n workflow** after confirming stability

---

## Design Decisions

### Why Standard Library Only?

- **Boring is good:** No dependencies = no version conflicts, no supply chain risk
- **Simple deployment:** Works everywhere Python 3.7+ runs
- **Easy auditing:** All code is in one file, easy to review

### Why Not Use `requests` or `httpx`?

- Standard library `urllib` is sufficient for simple HTTP requests
- Avoids dependency on external packages
- One less thing to install and manage

### Why Not Local State File?

- Database is the source of truth
- EVA API's `ON CONFLICT` clause handles deduplication perfectly
- Local state introduces complexity and failure modes
- We want ingestion to be stateless

### Why Conservative Filtering?

- Favor false negatives over false positives
- Better to miss marginal posts than to pollute the signal pipeline
- Filters:
  - Must have selftext (no link posts)
  - Must be > 10 characters
  - Must not be `[removed]` or `[deleted]`

---

## Troubleshooting

### "Connection refused" to eva-api:9080

**Cause:** Containers not running or not on same network.

**Fix:**
```bash
docker-compose up -d
docker network inspect eva_net  # Verify containers are on network
```

### "ModuleNotFoundError: No module named 'eva_ingest'"

**Cause:** Module not copied into eva_worker container.

**Fix:**
```bash
# Rebuild container
docker-compose build eva-worker
docker-compose up -d eva-worker
```

### HTTP 429 from Reddit

**Cause:** Rate limit exceeded.

**Fix:** Increase `--rate-limit-sleep` to 3-5 seconds, or reduce ingestion frequency.

---

## Future Enhancements (Not in v1)

- [ ] Reddit OAuth for higher rate limits
- [ ] Async/await for parallel subreddit fetching
- [ ] Dry-run mode (fetch but don't post)
- [ ] Configurable filtering rules
- [ ] Metrics export (Prometheus, StatsD)
- [ ] Multiple source support (Twitter, RSS, etc.)

---

## Summary

**What you get:**
- ✅ Deterministic, testable ingestion
- ✅ Clear logging and error handling
- ✅ Idempotent (safe to run multiple times)
- ✅ No external dependencies
- ✅ Complete documentation
- ✅ Easy to schedule (cron/systemd)
- ✅ Easy to validate (Makefile targets + SQL queries)

**What you DON'T get:**
- ❌ Auto-trading
- ❌ Recommendation changes
- ❌ Magic AI bullshit
- ❌ Fragile n8n workflows

**Philosophy:** Boring, deterministic, auditable. Local-first, human-gated.

---

## References

- **Main Script:** [eva_ingest/reddit_posts.py](eva_ingest/reddit_posts.py)
- **Documentation:** [docs/ingestion_reddit_posts.md](docs/ingestion_reddit_posts.md)
- **EVA API:** [eva-api/app.py](eva-api/app.py) (IntakeMessage model)
- **Database Schema:** [db/init.sql](db/init.sql) (raw_messages table)
- **Deprecated n8n Workflow:** [eva_worker/n8n_reddit_ingestion_posts_only.json](eva_worker/n8n_reddit_ingestion_posts_only.json)
