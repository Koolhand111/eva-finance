# EVA-Finance Phase 0 Validation - Execution Guide

## Goal
Prove that Reddit brand trends predict stock returns before proceeding with more infrastructure development.

## Success Criteria (from social-signal-trading skill)
- ✅ Win rate >55% at 3-6 month horizons
- ✅ Average returns >5% for winning trades
- ✅ At least 10 validated historical signals
- ✅ Clear time-to-profit pattern

## Execution Steps

### Step 1: Install Dependencies

```bash
pip install yfinance pandas numpy psycopg2-binary requests --break-system-packages
```

### Step 2: Apply Schema Patch (One-time)

Add UNIQUE constraint to prevent duplicate posts during backfill:

```bash
docker exec -it eva-db psql -U eva -d eva_finance -f /path/to/schema_patch_for_backfill.sql
```

Or manually:
```bash
docker exec -it eva-db psql -U eva -d eva_finance -c "ALTER TABLE raw_messages ADD CONSTRAINT raw_messages_source_platform_id_key UNIQUE (source, platform_id);"
```

### Step 3: Run Historical Backfill

### Step 3: Run Historical Backfill

This pulls 6-12 months of Reddit data from Pushshift API:

```bash
python reddit_historical_backfill.py
```

**What it does:**
- Fetches posts from 8 target subreddits
- Date range: 12 months ago → 1 month ago
- Inserts into `raw_messages` with `processed=false`
- Estimated time: 1-2 hours (rate limited)
- Expected volume: 5,000-20,000 posts depending on subreddit activity

**Monitor progress:**
```bash
# Check how many posts inserted
docker exec -it eva-db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM raw_messages WHERE processed=false;"

# Check date range
docker exec -it eva-db psql -U eva -d eva_finance -c "SELECT MIN(timestamp), MAX(timestamp) FROM raw_messages;"
```

### Step 4: Process Historical Data

Your existing `worker.py` will automatically process unprocessed messages:

```bash
# Check worker logs
docker logs eva-worker --tail 100 -f

# Or manually trigger if needed
docker exec -it eva-worker python worker.py
```

**What it does:**
- Extracts brands, behavioral tags, sentiment from historical posts
- Populates `processed_messages` table
- May take 30-60 minutes for 10k+ posts with LLM extraction

**Monitor extraction:**
```bash
# Check extraction progress
docker exec -it eva-db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM processed_messages;"

# Check unique brands found
docker exec -it eva-db psql -U eva -d eva_finance -c "SELECT DISTINCT unnest(brand) as brand FROM processed_messages ORDER BY brand;"
```

### Step 5: Run Backtest Analysis

Once extraction is complete:

```bash
python historical_backtest.py
```

**What it does:**
- Scans `processed_messages` for clear brand trends (2x+ mention increase)
- Maps brands to stock tickers
- Pulls historical stock data from Yahoo Finance
- Calculates returns at 30/60/90/180 day intervals
- Generates validation report with go/no-go decision

**Output files:**
- `backtest_results_YYYYMMDD_HHMMSS.csv` - Detailed results for each signal
- `backtest_analysis_YYYYMMDD_HHMMSS.json` - Summary metrics and decision

### Step 6: Review Results

```bash
# View latest analysis
cat backtest_analysis_*.json | jq .

# View detailed results
cat backtest_results_*.csv
```

## Decision Tree

### ✅ GO (Proceed to Phase 1)
**If all criteria met:**
- Win rate >55%
- Average returns >5%
- ≥10 validated signals

**Action:** Start Phase 1 (Critical Gaps) - Add brand materiality scoring, e-commerce data, Google Trends

### ⚠️ CAUTIOUS GO
**If 2 of 3 criteria met:**
- Shows promise but needs refinement

**Action:** Spend 1-2 weeks improving:
- Expand to more subreddits (increase signal volume)
- Lower confidence thresholds (capture more signals)
- Improve LLM extraction prompts

### ❌ NO-GO (Pivot or Abandon)
**If <2 criteria met:**
- Core thesis not validated
- Social signals don't predict returns

**Action:**
- Investigate why: Wrong subreddits? Wrong brands? Wrong time lag?
- Pivot to different approach (e.g., focus on news, not social)
- Or abandon investment strategy, pivot to different use case

## Troubleshooting

### Pushshift API Issues
**Problem:** Pushshift returns empty results or times out

**Solutions:**
- Try alternative: Use PRAW with `subreddit.top(time_filter='all', limit=1000)` for each subreddit
- Use Reddit archives from other sources (e.g., Academic Torrents)
- Reduce date range (try 6 months instead of 12)

### No Trends Detected
**Problem:** `detect_historical_trends()` finds <5 signals

**Solutions:**
- Lower `min_increase` threshold from 2.0 to 1.5 (50% increase instead of 2x)
- Lower `min_baseline_mentions` from 5 to 3
- Expand subreddit list (add r/running, r/frugalmalefashion, etc.)

### Stock Data Missing
**Problem:** `yfinance` can't find ticker

**Solutions:**
- Update `BRAND_TO_TICKER` mapping with correct tickers
- Check if company went public/private during timeframe
- Skip private companies (Patagonia, New Balance, etc.)

### LLM Extraction Slow
**Problem:** Processing 10k posts takes hours

**Solutions:**
- Run extraction overnight
- Increase `eva-worker` replicas in docker-compose
- Use OpenAI batch API for cheaper bulk processing

## Next Steps After Validation

### If GO Decision:
1. Commit backtest results to GitHub
2. Update roadmap status: Phase 0 ✅ → Phase 1 (in progress)
3. Start Phase 1 Week 1: Brand materiality scoring
4. Build brand → ticker resolver with revenue share tracking

### If NO-GO Decision:
1. Review detailed results: Which brands worked? Which failed?
2. Analyze failure modes: Time lag too long? Wrong sectors?
3. Iterate on signal detection before proceeding
4. Consider: Should we focus on different platforms (Twitter, news)?

## Timeline

**Optimistic:** 1 day total
- Backfill: 2 hours
- Extraction: 1 hour
- Backtest: 10 minutes
- Review: 30 minutes

**Realistic:** 2-3 days
- Backfill issues, debugging, waiting for extraction
- Multiple runs to tune thresholds
- Deep analysis of results

**Worst case:** 1 week
- Pushshift API problems
- Need to source alternative historical data
- Extensive debugging and threshold tuning
