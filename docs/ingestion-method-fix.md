# Ingestion Method Fix: AI Infrastructure Worker

**Date:** 2026-01-16
**Issue:** AI infrastructure worker was using PRAW (requires Reddit API credentials)
**Fix:** Updated to use Reddit's public JSON API (no credentials required)

---

## 1. Problem

The AI infrastructure worker was built using **PRAW** (Python Reddit API Wrapper), which requires:
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- Reddit API application registration

However, the existing consumer products ingestion (`eva_ingest/reddit_posts.py`) uses **Reddit's public JSON API**, which:
- Requires NO authentication
- Works immediately without any setup
- Is rate-limited but sufficient for our needs

---

## 2. Existing Method (eva_ingest/reddit_posts.py)

The consumer products worker uses this approach:

```python
# Public JSON endpoint - no auth required
url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"

request = Request(url, headers={"User-Agent": USER_AGENT})

with urlopen(request, timeout=30) as response:
    data = json.loads(response.read().decode("utf-8"))
    posts = [child["data"] for child in data["data"]["children"]]
```

**Key features:**
- Uses `urllib.request` (stdlib, no external dependencies)
- Rate limiting via `time.sleep()` between requests
- Custom User-Agent header
- 30-second timeout

---

## 3. Changes Made

### requirements.txt
**Before:**
```
praw==7.7.1
psycopg2-binary==2.9.9
python-dotenv==1.0.0
```

**After:**
```
psycopg2-binary==2.9.9
python-dotenv==1.0.0
```

Removed: `praw` (no longer needed)

### config.py
**Before:**
```python
DATABASE_URL = os.getenv('DATABASE_URL')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', '...')
```

**After:**
```python
DATABASE_URL = os.getenv('DATABASE_URL')
ENABLED = os.getenv('AI_INFRA_ENABLED', 'false').lower() == 'true'
LOOP_INTERVAL_SECONDS = 15 * 60
POSTS_PER_SUBREDDIT = 50
USER_AGENT = "EVA-Finance/1.0 (AI Infrastructure Monitor; boring and deterministic)"
RATE_LIMIT_SLEEP = 2  # seconds between subreddit fetches
```

Removed: All Reddit API credential references
Added: `USER_AGENT`, `RATE_LIMIT_SLEEP` for public API

### reddit_client.py
**Before:** PRAW-based client requiring authentication
**After:** Public JSON API client matching `eva_ingest/reddit_posts.py`

Key changes:
- Removed `praw` import
- Added `urllib.request` for HTTP requests
- Added rate limiting between requests
- Uses `https://www.reddit.com/r/{subreddit}/new.json` endpoint

### docker-compose.yml
**Before:**
```yaml
environment:
  - DATABASE_URL=${DATABASE_URL}
  - REDDIT_CLIENT_ID=${REDDIT_CLIENT_ID}
  - REDDIT_CLIENT_SECRET=${REDDIT_CLIENT_SECRET}
  - REDDIT_USER_AGENT=EVA-Finance AI Infrastructure Monitor
  - AI_INFRA_ENABLED=true
```

**After:**
```yaml
environment:
  - DATABASE_URL=${DATABASE_URL}
  - AI_INFRA_ENABLED=true
```

Removed: All Reddit credential environment variables

---

## 4. Dependency Comparison

| Dependency | Consumer Products | AI Infrastructure (Fixed) |
|------------|-------------------|---------------------------|
| praw | ❌ Not used | ❌ Removed |
| psycopg2-binary | ✅ Used | ✅ Used |
| python-dotenv | ✅ Used | ✅ Used |
| urllib.request | ✅ Used (stdlib) | ✅ Used (stdlib) |

---

## 5. Rebuild Instructions

```bash
# 1. Rebuild the container with new dependencies
docker compose build eva-ai-infrastructure-worker

# 2. Restart the container
docker compose up -d eva-ai-infrastructure-worker

# 3. Monitor logs to verify it's working
docker compose logs -f eva-ai-infrastructure-worker
```

**Expected startup output:**
```
============================================================
AI Infrastructure Raw Ingestion STARTING
Timestamp: 2026-01-16 ...
Mode: RAW INGESTION ONLY (no LLM extraction)
============================================================
Monitoring 5 subreddits: datacenter, sysadmin, homelab, LocalLLaMA, MachineLearning
...
[2026-01-16 ...] Loop #1 starting...
  Fetching r/datacenter...
    ✓ 50 posts fetched, 50 new, 0 duplicates
```

---

## 6. Verification

After rebuild, verify no credential errors:

```bash
# Should NOT see any "REDDIT_CLIENT_ID" or auth errors
docker compose logs eva-ai-infrastructure-worker 2>&1 | grep -i "auth\|credential\|client_id"
```

Check data is being collected:
```bash
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT subreddit, COUNT(*) FROM ai_infrastructure_raw_posts GROUP BY subreddit;"
```

---

## 7. Summary

| Aspect | Before | After |
|--------|--------|-------|
| Auth method | PRAW (OAuth) | Public JSON API |
| Credentials needed | Yes (3 env vars) | No |
| External dependencies | praw | None (stdlib only) |
| Matches consumer products | ❌ No | ✅ Yes |
