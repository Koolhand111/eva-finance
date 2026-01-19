# Task 4 Monitoring: AI Infrastructure Worker

**Date:** 2026-01-16
**Status:** ENABLED (AI_INFRA_ENABLED=true)

---

## 1. Restart the Worker

After enabling, rebuild and restart the container:

```bash
# Rebuild with new config
docker compose build eva-ai-infrastructure-worker

# Restart the container
docker compose up -d eva-ai-infrastructure-worker
```

---

## 2. Monitor Worker Logs

### Live log stream (Ctrl+C to exit)
```bash
docker compose logs -f eva-ai-infrastructure-worker
```

### Recent logs
```bash
docker compose logs eva-ai-infrastructure-worker --tail 50
```

### Expected startup output
```
============================================================
AI Infrastructure Raw Ingestion STARTING
Timestamp: 2026-01-16 ...
Mode: RAW INGESTION ONLY (no LLM extraction)
============================================================
Monitoring 5 subreddits: datacenter, sysadmin, homelab, LocalLLaMA, MachineLearning
Fetching 50 posts per subreddit
Loop interval: 900s (15 minutes)

[2026-01-16 ...] Loop #1 starting...
  Fetching r/datacenter...
    ✓ 50 posts fetched, 50 new, 0 duplicates
  ...
```

---

## 3. Verify Post Collection (SQL Queries)

Run after 30+ minutes to verify data is being collected:

```bash
docker exec eva_db psql -U eva -d eva_finance
```

### Check post collection by subreddit
```sql
SELECT
  subreddit,
  COUNT(*) as posts,
  MIN(created_at) as first_post,
  MAX(created_at) as latest_post
FROM ai_infrastructure_raw_posts
GROUP BY subreddit
ORDER BY posts DESC;
```

**Expected output (after first loop):**
```
    subreddit     | posts |       first_post       |      latest_post
------------------+-------+------------------------+------------------------
 sysadmin         |    50 | 2026-01-16 ...         | 2026-01-16 ...
 LocalLLaMA       |    50 | 2026-01-16 ...         | 2026-01-16 ...
 MachineLearning  |    50 | 2026-01-16 ...         | 2026-01-16 ...
 homelab          |    50 | 2026-01-16 ...         | 2026-01-16 ...
 datacenter       |    50 | 2026-01-16 ...         | 2026-01-16 ...
```

### Recent posts sample
```sql
SELECT subreddit, LEFT(title, 60) as title, created_at
FROM ai_infrastructure_raw_posts
ORDER BY created_at DESC
LIMIT 10;
```

### Total post count
```sql
SELECT COUNT(*) as total_posts FROM ai_infrastructure_raw_posts;
```

### Posts collected in last hour
```sql
SELECT COUNT(*) as recent_posts
FROM ai_infrastructure_raw_posts
WHERE created_at > NOW() - INTERVAL '1 hour';
```

---

## 4. Verify Consumer Products Health

### Check all containers running
```bash
docker compose ps
```

### Check consumer worker logs
```bash
docker compose logs eva-worker --tail 20
```

**Expected:** Normal polling behavior, no errors

### Check consumer API health
```bash
curl -s http://localhost:9080/health
```

**Expected:** `{"status": "healthy"}` or similar

### Quick consumer products SQL check
```bash
docker exec eva_db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM raw_messages WHERE created_at > NOW() - INTERVAL '1 hour';"
```

---

## 5. Troubleshooting

### Worker not starting
```bash
# Check container status
docker compose ps eva-ai-infrastructure-worker

# Check for build errors
docker compose build eva-ai-infrastructure-worker 2>&1 | tail -30

# Check container logs for errors
docker compose logs eva-ai-infrastructure-worker 2>&1 | head -50
```

### No posts being collected
1. Check Reddit credentials in `.env`:
   ```bash
   grep REDDIT .env
   ```
2. Verify credentials are set (should show values, not blank):
   ```bash
   docker compose exec eva-ai-infrastructure-worker env | grep REDDIT
   ```
3. Check for Reddit API errors in logs:
   ```bash
   docker compose logs eva-ai-infrastructure-worker | grep -i error
   ```

### Database connection issues
```bash
# Test database connectivity
docker compose exec eva-ai-infrastructure-worker python -c "from db_client import DatabaseClient; db = DatabaseClient(); print(db.get_active_subreddits())"
```

---

## 6. Rollback (Disable Worker)

To disable the worker without stopping it:

### Option A: Edit docker-compose.yml
Change:
```yaml
- AI_INFRA_ENABLED=true  # ENABLED - collecting data
```
To:
```yaml
- AI_INFRA_ENABLED=false  # KILL SWITCH - disabled
```

Then restart:
```bash
docker compose up -d eva-ai-infrastructure-worker
```

### Option B: Stop the container entirely
```bash
docker compose stop eva-ai-infrastructure-worker
```

---

## 7. Success Criteria Checklist

| Check | Command | Expected |
|-------|---------|----------|
| Worker running | `docker compose ps` | `eva_ai_infra_worker` Up |
| Startup message shows "STARTING" | `docker compose logs ... \| head -10` | No "DISABLED" message |
| Posts being collected | SQL query above | 50+ posts per subreddit |
| No duplicate errors | Logs | Duplicates skipped silently |
| Consumer worker healthy | `docker compose logs eva-worker` | Normal polling |
| Consumer API healthy | `curl localhost:9080/health` | 200 OK |

---

## 8. Monitoring Schedule

| Time | Action |
|------|--------|
| T+0 | Restart worker, verify startup logs |
| T+5min | Check logs for first loop completion |
| T+15min | Verify second loop starts |
| T+30min | Run SQL queries to verify data collection |
| T+1hr | Confirm consumer products still healthy |
