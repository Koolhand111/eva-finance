# Task 3 Verification: AI Infrastructure Worker Docker Service

**Date:** 2026-01-16
**Status:** Ready for verification

---

## 1. Verification Commands

Run these commands to verify the AI infrastructure worker is correctly configured:

### Step 1: Build the new container
```bash
docker compose build eva-ai-infrastructure-worker
```

**Expected output:**
- Build completes successfully
- Python 3.11-slim base image pulled
- Dependencies installed (praw, psycopg2-binary, python-dotenv)

### Step 2: Start the new container (disabled mode)
```bash
docker compose up -d eva-ai-infrastructure-worker
```

**Expected output:**
- Container starts
- No errors

### Step 3: Check it's running but disabled
```bash
docker compose logs eva-ai-infrastructure-worker | head -20
```

**Expected output:**
```
============================================================
AI Infrastructure Worker is DISABLED
Set AI_INFRA_ENABLED=true in docker-compose.yml to activate
============================================================
```

### Step 4: Verify all containers are running
```bash
docker compose ps
```

**Expected output:**
- `eva_ai_infra_worker` - Running (disabled mode)
- `eva_worker` - Running (consumer products)
- `eva_api` - Running (healthy)
- `eva_db` - Running
- All other services unchanged

### Step 5: Verify consumer products worker still healthy
```bash
docker compose logs eva-worker | tail -10
```

**Expected output:**
- Normal polling logs
- `[EVA-NOTIFY] No pending notifications` or similar
- No errors

---

## 2. Service Configuration Summary

| Setting | Value |
|---------|-------|
| Service name | `eva-ai-infrastructure-worker` |
| Container name | `eva_ai_infra_worker` |
| Build context | `./workers/ai-infrastructure` |
| Kill switch | `AI_INFRA_ENABLED=false` (DISABLED) |
| Depends on | `db` |
| Network | `eva_net` |

---

## 3. Environment Variables Required

Before enabling the worker (Task 4), these must be added to `.env`:

```bash
REDDIT_CLIENT_ID=<your-reddit-client-id>
REDDIT_CLIENT_SECRET=<your-reddit-client-secret>
```

---

## 4. Checklist

| Check | Status |
|-------|--------|
| docker-compose.yml syntax valid | ✅ Verified |
| New service added | ✅ Added |
| Existing services unchanged | ✅ Confirmed |
| Kill switch default = false | ✅ Confirmed |
| Container builds successfully | ⏳ Run Step 1 |
| Container starts in disabled mode | ⏳ Run Step 2-3 |
| Consumer products unaffected | ⏳ Run Step 4-5 |

---

## 5. Rollback (if needed)

To remove the AI infrastructure worker:

```bash
# Stop and remove the container
docker compose stop eva-ai-infrastructure-worker
docker compose rm -f eva-ai-infrastructure-worker

# Remove the image
docker rmi eva-finance-eva-ai-infrastructure-worker
```

The service can then be commented out or removed from docker-compose.yml.
