# n8n Reddit Ingestion Setup Instructions

## Overview
This workflow automatically ingests Reddit posts from configured subreddits into EVA-Finance every 15 minutes.

**Current Status**: Posts-only implementation (comments will be added in future iteration)

## Prerequisites
- n8n running and accessible at http://localhost:5678
- n8n container connected to `eva-finance_eva_net` Docker network
- EVA API accessible at `http://eva-api:9080` from n8n container

## Import Workflow

1. **Access n8n UI**
   ```bash
   # Open in browser
   open http://localhost:5678
   ```

2. **Import the Workflow**
   - Click "Add workflow" button (top right)
   - Click the "..." menu → "Import from File"
   - Select: `eva_worker/n8n_reddit_ingestion_posts_only.json`
   - Workflow should open with 10 nodes configured

3. **Verify Configuration**
   - **Schedule Trigger**: Every 15 minutes
   - **Subreddits**: BuyItForLife, Frugal, running (edit in "Create Subreddit List" node)
   - **EVA API URL**: `http://eva-api:9080/intake/message`

## Test Workflow Manually

1. **Execute Test Run**
   - Click "Execute workflow" button (top right)
   - Watch nodes turn green as they execute
   - Check execution panel (bottom) for output

2. **Expected Behavior**
   - Fetches ~25 posts from each of 3 subreddits
   - Filters to text-only posts
   - POSTs each post individually to EVA API
   - Should process 30-75 messages total

3. **Verify in Database**
   ```bash
   # Check messages ingested
   docker exec eva_db psql -U eva -d eva_finance -c \
     "SELECT COUNT(*), source FROM raw_messages GROUP BY source;"

   # Should show 'reddit' as source with message count
   ```

## Activate Scheduled Execution

1. **Turn on Workflow**
   - Toggle "Active" switch (top right of workflow)
   - Workflow will now run automatically every 15 minutes

2. **Monitor Executions**
   - Click "Executions" tab
   - View past runs, success/failure status
   - Click on execution to see detailed logs

## Troubleshooting

### Error: "Connection refused to eva-api"

**Cause**: n8n cannot reach EVA API

**Fix**:
```bash
# Verify n8n is on correct network
docker inspect n8n | grep -A 5 Networks

# Should show: eva-finance_eva_net

# If not, connect it:
docker network connect eva-finance_eva_net n8n
```

### Error: "Rate limit exceeded"

**Cause**: Reddit API limits ~30 requests/minute for anonymous

**Fix**:
- Increase schedule interval to 30+ minutes
- Or add "Wait" node (10 seconds) after HTTP Fetch Posts

### Error: "Empty response from Reddit"

**Cause**: Subreddit has low activity or API issue

**Fix**:
- Check Code: Extract Posts node - it handles empty responses gracefully
- Verify Reddit API: https://www.reddit.com/r/BuyItForLife/new.json

### Posts not being processed

**Cause**: Worker might not be running

**Fix**:
```bash
# Check worker logs
docker compose logs eva_worker --tail 50

# Verify worker is processing
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT COUNT(*), processed FROM raw_messages GROUP BY processed;"
```

## Workflow Structure

```
Schedule Trigger (every 15min)
  ↓
Create Subreddit List (3 subreddits)
  ↓
Split Subreddits ─────┐
  ↓                   │ (outer loop)
HTTP: Fetch Posts     │
  ↓                   │
Extract Posts         │
  ↓                   │
Split Posts ─────┐    │
  ↓              │    │ (inner loop)
Format for EVA   │    │
  ↓              │    │
POST to EVA      │    │
  ↓              │    │
Merge Posts ─────┘    │
  ↓                   │
Merge Subreddits ─────┘
```

## Customization

### Add More Subreddits

Edit "Create Subreddit List" node:
```javascript
return [
  { subreddit: 'BuyItForLife' },
  { subreddit: 'Frugal' },
  { subreddit: 'running' },
  { subreddit: 'MakeupAddiction' },  // Add more here
];
```

### Change Schedule Interval

Edit "Schedule Every 15min" node:
- Change interval from 15 minutes to desired value
- Recommended: 15-30 minutes to respect Reddit rate limits

### Filter Posts by Keywords

Add filtering in "Extract Posts" node:
```javascript
.filter(post => {
  const text = `${post.title} ${post.selftext}`.toLowerCase();
  return text.includes('brand') || text.includes('switch');
})
```

## Monitoring

### Watch Ingestion Live

```bash
# Real-time message count
watch -n 10 'docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT COUNT(*), MAX(created_at) FROM raw_messages WHERE source='"'"'reddit'"'"';"'

# Real-time processing
watch -n 10 'docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT COUNT(*), processor_version FROM processed_messages GROUP BY processor_version;"'
```

### Check Extracted Data

```bash
# Top brands extracted
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT brand, COUNT(*) FROM processed_messages, unnest(brand) as brand \
   WHERE created_at > NOW() - INTERVAL '2 hours' \
   GROUP BY brand ORDER BY COUNT(*) DESC LIMIT 20;"

# Top tags extracted
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT tag, COUNT(*) FROM processed_messages, unnest(tags) as tag \
   WHERE created_at > NOW() - INTERVAL '2 hours' \
   GROUP BY tag ORDER BY COUNT(*) DESC LIMIT 20;"
```

## Next Steps

Once posts-only ingestion is stable:
1. Add Reddit comments (nested loop implementation)
2. Implement deduplication (check platform_id before POST)
3. Add error retry logic
4. Monitor for Reddit API changes

## Support

If issues persist:
1. Check n8n execution logs
2. Verify EVA worker logs: `docker compose logs eva_worker`
3. Test EVA API manually: `curl http://localhost:9080/health`
