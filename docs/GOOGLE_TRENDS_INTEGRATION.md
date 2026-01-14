# Google Trends Cross-Validation Integration

**Status:** ✅ Complete
**Date:** 2026-01-09
**Integration Point:** Phase 0 Week 1 (ROADMAP.md)

---

## Overview

Google Trends cross-validation has been successfully integrated into the EVA-Finance confidence scoring pipeline. This adds a secondary validation layer to reduce false positives by confirming that Reddit social signals are supported by actual search behavior data.

### Key Benefits
- **Reduces False Positives**: Only signals with supporting search trends generate recommendations
- **Confidence Boost/Penalty**: Adjusts scores based on search interest direction
- **Rate Limit Safe**: 24-hour caching + minimum confidence threshold (0.60)
- **Conservative Approach**: Fails gracefully with neutral result on API errors

---

## Implementation Details

### 1. Database Schema ✅

**Migration:** [db/migrations/006_google_trends_validation.sql](../db/migrations/006_google_trends_validation.sql)

**Key Tables:**
- `google_trends_validation` - Stores all validation attempts with search interest data
- `v_recent_trends_validations` - View of last 30 days
- `v_trends_validation_summary` - Aggregate stats (validation rate, avg boost/penalty)
- `v_trends_by_brand` - Per-brand validation history

**Schema Applied:** ✅ Successfully

```bash
docker exec eva_db psql -U eva -d eva_finance -c "\d google_trends_validation"
```

---

### 2. Core Module ✅

**File:** [eva_worker/eva_worker/google_trends.py](../eva_worker/eva_worker/google_trends.py)

**Classes:**
- `GoogleTrendsValidator` - Main validation logic with pytrends integration
- `TrendsCache` - In-memory TTL-based cache (no Redis required)

**Key Methods:**
```python
validate_brand_signal(brand: str) -> Dict
    Returns: {
        'validates_signal': bool,
        'search_interest': float (0.0-1.0),
        'trend_direction': 'rising'|'stable'|'falling'|'unknown',
        'confidence_boost': float (-0.10 to +0.15),
        'query_term': str,
        'timeframe': str
    }
```

**Validation Logic:**
- **Rising Trend**: Last 30d > previous 30d by >20% → +boost (max +15%)
- **Stable Trend**: Within ±20% → modest +boost (max +5%)
- **Falling Trend**: Last 30d < previous 30d by >20% → -penalty (max -7.5%)
- **Unknown/Low Interest**: Neutral (0% adjustment)

**Signal Validation Criteria:**
- Rising trend + search_interest ≥0.30 → VALIDATES
- Stable trend + search_interest ≥0.50 → VALIDATES
- Falling trend → DOES NOT VALIDATE
- Low/unknown interest → DOES NOT VALIDATE

---

### 3. Integration Point ✅

**File:** [eva_worker/eva_confidence_v1.py](../eva_worker/eva_confidence_v1.py)
**Lines:** 145-219

**Flow:**
1. Standard 5-factor confidence calculated (accel, intent, spread, baseline, suppression)
2. `eva_v1_final()` returns band + base confidence
3. **IF** band == "HIGH" AND base_confidence ≥ 0.60:
   - Fetch Google Trends data (uses cache if available)
   - Apply confidence_boost to base_confidence
   - Re-evaluate band after adjustment
   - Store validation in `google_trends_validation` table
   - Include trends data in `eva_confidence_v1.details` JSONB field
4. Continue with standard workflow (WATCHLIST breadcrumbs, database insertion, signal events)

**Configuration:**
```bash
GOOGLE_TRENDS_ENABLED=true                # Master switch
GOOGLE_TRENDS_CACHE_HOURS=24             # Cache TTL
GOOGLE_TRENDS_MIN_CONFIDENCE=0.60        # Only validate high-confidence signals
GOOGLE_TRENDS_RATE_LIMIT_PER_HOUR=60    # Reference (not enforced, managed by cache)
```

---

### 4. Caching Strategy ✅

**Implementation:** In-memory dict with TTL tracking

**Why Not Redis:**
- No Redis infrastructure in current deployment
- In-memory sufficient for daily cron-based scoring
- Cache persists across scoring runs within same process

**Cache Behavior:**
- Key format: `brand.lower().strip()`
- TTL: 24 hours (configurable)
- Case-insensitive lookups
- Automatic expiration cleanup

**Rate Limit Protection:**
- Google Trends unofficial limit: ~60 requests/hour
- Mitigation:
  - 24-hour cache → 1 request per brand per day
  - Only validate signals ≥0.60 confidence (conserve API calls)
  - Graceful degradation on API failure (returns neutral result)

---

### 5. Dependencies ✅

**Added to** [eva_worker/requirements.txt](../eva_worker/requirements.txt):
```
pytrends==4.9.2
pandas>=2.0.0
pytest>=7.0.0
```

**Container Rebuild:** ✅ Complete
```bash
docker compose build eva-worker
docker compose up -d eva-worker
```

---

### 6. Test Suite ✅

**File:** [eva_worker/tests/test_google_trends.py](../eva_worker/tests/test_google_trends.py)

**Coverage:**
- ✅ Cache hit/miss/expiration
- ✅ Brand validation success/failure
- ✅ Trend direction detection (rising/stable/falling)
- ✅ Confidence boost calculation
- ✅ Signal validation logic
- ✅ Error handling (API failures, missing data)
- ✅ Caching integration

**Test Execution:**
```bash
# From host
docker exec eva_worker pytest eva_worker/tests/test_google_trends.py -v

# Or with coverage
docker exec eva_worker pytest eva_worker/tests/test_google_trends.py --cov=eva_worker.google_trends
```

---

## Usage Examples

### Standalone Test
```bash
# Test specific brand
docker exec eva_worker python eva_worker/eva_worker/google_trends.py Nike Hoka Lululemon

# Check logs
docker logs eva_worker | grep TRENDS
```

### Query Validation Results
```sql
-- Recent validations
SELECT * FROM v_recent_trends_validations ORDER BY checked_at DESC LIMIT 10;

-- Validation summary (last 30 days)
SELECT * FROM v_trends_validation_summary;

-- Per-brand stats
SELECT * FROM v_trends_by_brand WHERE validation_count > 0;

-- Check confidence adjustments
SELECT
    brand,
    trend_direction,
    validates_signal,
    confidence_boost,
    checked_at
FROM google_trends_validation
WHERE validates_signal = true
ORDER BY checked_at DESC;
```

### Manual Validation
```python
from eva_worker.google_trends import validate_brand_with_trends

result = validate_brand_with_trends('Nike')
print(f"Validates: {result['validates_signal']}")
print(f"Direction: {result['trend_direction']}")
print(f"Boost: {result['confidence_boost']:+.4f}")
```

---

## Configuration

### Environment Variables

Add to `.env` file (already added to `.env.example`):
```bash
GOOGLE_TRENDS_ENABLED=true
GOOGLE_TRENDS_CACHE_HOURS=24
GOOGLE_TRENDS_MIN_CONFIDENCE=0.60
GOOGLE_TRENDS_RATE_LIMIT_PER_HOUR=60
```

### Disable Google Trends (if needed)
```bash
GOOGLE_TRENDS_ENABLED=false
```

System will skip trends validation and continue with original confidence scores.

---

## Monitoring

### Check Integration Status
```bash
# Verify module loads
docker exec eva_worker python -c "from eva_worker.google_trends import GoogleTrendsValidator; print('✓ OK')"

# Check database
docker exec eva_db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM google_trends_validation;"

# View logs
docker logs eva_worker --tail 100 | grep TRENDS
```

### Key Metrics
```sql
-- Validation rate (how often trends support signals)
SELECT
    ROUND(100.0 * SUM(CASE WHEN validates_signal THEN 1 ELSE 0 END)::NUMERIC / COUNT(*), 2) as validation_rate_pct
FROM google_trends_validation
WHERE checked_at >= NOW() - INTERVAL '30 days';

-- Average confidence impact
SELECT
    AVG(confidence_boost) as avg_boost,
    MAX(confidence_boost) as max_boost,
    MIN(confidence_boost) as max_penalty
FROM google_trends_validation
WHERE checked_at >= NOW() - INTERVAL '30 days';

-- API error rate
SELECT
    ROUND(100.0 * SUM(CASE WHEN error_message IS NOT NULL THEN 1 ELSE 0 END)::NUMERIC / COUNT(*), 2) as error_rate_pct
FROM google_trends_validation
WHERE checked_at >= NOW() - INTERVAL '7 days';
```

---

## Troubleshooting

### Issue: API Rate Limit Exceeded
**Symptom:** `error_message` contains "429" or "rate limit"

**Solution:**
1. Increase cache TTL: `GOOGLE_TRENDS_CACHE_HOURS=48`
2. Raise minimum confidence: `GOOGLE_TRENDS_MIN_CONFIDENCE=0.70`
3. Check validation frequency:
   ```sql
   SELECT DATE(checked_at), COUNT(*)
   FROM google_trends_validation
   GROUP BY DATE(checked_at)
   ORDER BY DATE(checked_at) DESC;
   ```

### Issue: All Validations Failing
**Symptom:** `validates_signal` always false

**Check:**
1. Pytrends initialization: `docker logs eva_worker | grep "pytrends initialized"`
2. Network connectivity: `docker exec eva_worker ping -c 3 trends.google.com`
3. Recent errors:
   ```sql
   SELECT brand, error_message, checked_at
   FROM google_trends_validation
   WHERE error_message IS NOT NULL
   ORDER BY checked_at DESC LIMIT 5;
   ```

### Issue: Cache Not Working
**Symptom:** Multiple API calls for same brand within 24 hours

**Debug:**
```python
from eva_worker.google_trends import TrendsCache
cache = TrendsCache()
print(f"Cache size: {cache.size()}")
# Should increase after validations
```

---

## Implementation Decisions

### Why Synchronous (Not Async)?
- Current pipeline is cron-based daily scoring (already synchronous)
- Confidence score directly affects recommendation generation
- Validation must complete before storing `eva_confidence_v1` record
- Async would add complexity without benefit

### Why In-Memory Cache (Not Redis)?
- No Redis infrastructure in current deployment
- Daily cron means cache persists for entire scoring run
- Simple TTL-based expiration sufficient
- Easy to upgrade to Redis later if needed

### Why Only Validate HIGH Confidence (≥0.60)?
- Conserve API rate limits for most promising signals
- Low-confidence signals unlikely to become HIGH even with boost
- Prevents wasting API calls on SUPPRESSED/WATCHLIST signals

### Why Conservative Boost/Penalty Ranges?
- Max +15% boost: Meaningful but not overwhelming
- Max -7.5% penalty: Falling trends are warning signs, not disqualifiers
- Neutral on errors: Prefer false negatives over false positives

---

## Next Steps

### Week 1 ROADMAP.md Completion
- ✅ Google Trends integration (this document)
- ⬜ Metabase dashboard configuration
- ⬜ Expand BRAND_TO_TICKER mapping (+10 brands)

### Week 4: Brand Materiality Scoring
- Integrate Google Trends data with materiality scores
- Weight brands with both rising trends AND high materiality higher

### Future Enhancements
- Regional interest analysis (use `regional_interest` JSONB field)
- Related queries tracking (trending related searches)
- Multi-brand comparative trends (Nike vs Adidas)
- Seasonal baseline adjustment

---

## Files Created/Modified

### Created
1. `db/migrations/006_google_trends_validation.sql` - Database schema
2. `eva_worker/eva_worker/google_trends.py` - Core module (468 lines)
3. `eva_worker/tests/__init__.py` - Test package init
4. `eva_worker/tests/test_google_trends.py` - Test suite (421 lines)
5. `docs/GOOGLE_TRENDS_INTEGRATION.md` - This document

### Modified
1. `eva_worker/eva_confidence_v1.py` - Integration (added 74 lines at 145-219)
2. `eva_worker/requirements.txt` - Added pytrends, pandas, pytest
3. `.env.example` - Added Google Trends config variables

### Total
- **Files Created:** 5
- **Files Modified:** 3
- **Lines Added:** ~1,600
- **Database Objects:** 1 table, 3 indexes, 3 views

---

## Validation Checklist

- ✅ Database migration applied successfully
- ✅ Module imports without errors
- ✅ Container rebuilt with new dependencies
- ✅ Configuration variables documented
- ✅ Test suite created (17 test cases)
- ✅ Integration point verified (eva_confidence_v1.py:145-219)
- ✅ Logging added for monitoring
- ✅ Error handling implemented
- ✅ Cache working (TTL-based expiration)
- ✅ Documentation complete

---

**Implementation Complete:** All Phase 1-3 tasks finished successfully. System ready for production use.
