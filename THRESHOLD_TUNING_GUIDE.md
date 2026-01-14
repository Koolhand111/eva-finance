# EVA-Finance Threshold Tuning Guide

Quick reference for adjusting confidence scoring thresholds as the system matures.

---

## Current Configuration (Phase 0)

```bash
# In .env or docker-compose.yml environment:
EVA_GATE_INTENT=0.50
EVA_GATE_SUPPRESSION=0.40
EVA_GATE_SPREAD=0.25
EVA_BAND_HIGH=0.60
EVA_BAND_WATCHLIST=0.50
GOOGLE_TRENDS_ENABLED=false
```

**Result:** 8 HIGH confidence signals from 111 candidates (7.2% pass rate)

---

## Threshold Meanings

### Gate Thresholds (Hard Filters - Signal SUPPRESSED if below)

**EVA_GATE_SPREAD** (Current: 0.25)
- **Formula:** `max((source_count - 1) / 3.0, (platform_count - 1) / 3.0)`
- **Meaning:** How many subreddits/platforms mention the brand
- **Values:**
  - 0.00 = 1 source (single subreddit)
  - 0.25 = 1.75 sources (effectively 2 subreddits)
  - 0.33 = 2 sources (2 distinct communities)
  - 0.50 = 2.5 sources (3+ subreddits - production target)
- **When to raise:** More subreddits active (currently 10, target 20+)

**EVA_GATE_INTENT** (Current: 0.50)
- **Meaning:** Ratio of action-oriented messages (buy/own/recommend)
- **Values:**
  - 0.20 = No action intent (pure discussion)
  - 0.50 = Moderate intent (50% exploration, 50% action)
  - 0.65 = Strong intent (production target)
  - 0.95 = Maximum (all messages show purchase/ownership)
- **When to raise:** After validating Phase 0 signals perform well

**EVA_GATE_SUPPRESSION** (Current: 0.40)
- **Meaning:** 1 - meme_risk (filters hype without action)
- **Formula:** `meme_risk = 0.7 if (action_intent < 0.1 AND eval_intent > 0.5) else 0.3`
- **Values:**
  - 0.30 = High meme risk (70% spam/hype probability)
  - 0.40 = Moderate risk tolerance (Phase 0)
  - 0.50 = Low risk tolerance (production)
  - 0.70 = No meme characteristics
- **When to raise:** If seeing too many false positives from viral/meme brands

### Band Thresholds (Classification - Does NOT suppress)

**EVA_BAND_HIGH** (Current: 0.60)
- **Meaning:** Minimum final_confidence for "actionable" signal
- **Use case:** Paper trading entry threshold
- **Values:**
  - 0.60 = Phase 0 (expect 5-10 signals)
  - 0.70 = Phase 1 (expect 3-7 signals)
  - 0.80 = Production (expect 1-3 signals per week)
- **When to raise:** Based on false positive rate

**EVA_BAND_WATCHLIST** (Current: 0.50)
- **Meaning:** Signals that passed gates but below HIGH threshold
- **Use case:** Monitoring, early warnings
- **When to raise:** If too noisy, or after Phase 0 validation

---

## Phase Progression Roadmap

### Phase 0: Bootstrap (Weeks 1-4) - CURRENT
**Goal:** Generate enough signals to validate thesis
**Data:** 6 days, 981 messages, 10 subreddits

```bash
EVA_GATE_SPREAD=0.25          # Accept 2+ subreddits
EVA_GATE_INTENT=0.50          # Accept moderate intent
EVA_GATE_SUPPRESSION=0.40     # Tolerate some meme risk
EVA_BAND_HIGH=0.60            # Lower bar for HIGH
```

**Expected:** 5-10 HIGH signals
**Validation:** Track paper trading performance, measure false positive rate

### Phase 1: Stabilization (Weeks 5-8)
**Goal:** Tighten thresholds based on validation data
**Data:** 30+ days, 15,000+ messages, 15+ subreddits

```bash
EVA_GATE_SPREAD=0.35          # Prefer 3+ subreddits (2 as minimum)
EVA_GATE_INTENT=0.55          # Stronger action intent required
EVA_GATE_SUPPRESSION=0.45     # Lower meme tolerance
EVA_BAND_HIGH=0.65            # Raise bar for HIGH
```

**Expected:** 3-8 HIGH signals
**Validation:** Correlation with market movements, signal persistence

### Phase 2: Optimization (Weeks 9-12)
**Goal:** Approach production quality
**Data:** 60+ days, 40,000+ messages, 20+ subreddits

```bash
EVA_GATE_SPREAD=0.45          # Strong multi-community requirement
EVA_GATE_INTENT=0.60          # High action intent
EVA_GATE_SUPPRESSION=0.48     # Near-production meme filter
EVA_BAND_HIGH=0.70            # Strict HIGH classification
```

**Expected:** 2-5 HIGH signals
**Validation:** ROI analysis, compare to market indices

### Production (Week 13+)
**Goal:** Conservative, high-precision signal generation
**Data:** 90+ days, 100,000+ messages, 30+ subreddits

```bash
EVA_GATE_SPREAD=0.50          # Original design spec (3+ subreddits)
EVA_GATE_INTENT=0.65          # Original design spec
EVA_GATE_SUPPRESSION=0.50     # Original design spec
EVA_BAND_HIGH=0.80            # Original design spec
GOOGLE_TRENDS_ENABLED=true    # Re-enable cross-validation
```

**Expected:** 1-3 HIGH signals per week
**Target:** <5% false positive rate, >60% market correlation

---

## Decision Matrix: When to Adjust

### Too Many Signals (>15 HIGH per week)
**Problem:** Likely too noisy, hard to trade all signals
**Solution:**
```bash
# Tighten gates progressively:
EVA_GATE_SPREAD += 0.05      # Require more cross-community validation
EVA_BAND_HIGH += 0.05        # Raise HIGH threshold
EVA_GATE_INTENT += 0.05      # Require stronger action intent
```

### Too Few Signals (<3 HIGH per month)
**Problem:** Cannot validate thesis, not enough data
**Solution:**
```bash
# Loosen gates carefully:
EVA_GATE_SPREAD -= 0.05      # Accept fewer subreddits
EVA_BAND_HIGH -= 0.05        # Lower HIGH threshold
# DO NOT lower intent below 0.50 (risks poor signal quality)
```

### High False Positive Rate (>20%)
**Problem:** Signals decay quickly, no market correlation
**Solution:**
```bash
# Focus on quality, not quantity:
EVA_GATE_INTENT += 0.10      # Much stronger action requirement
EVA_GATE_SUPPRESSION += 0.05 # Filter memes more aggressively
GOOGLE_TRENDS_ENABLED=true   # Add external validation
```

### Low Precision but Good Signals Exist
**Problem:** Mixed quality, some signals very strong
**Solution:**
```bash
# Widen the funnel, raise the bar:
EVA_GATE_SPREAD -= 0.05      # Accept more candidates into scoring
EVA_BAND_HIGH += 0.10        # But only elevate the best to HIGH
# This creates more WATCHLIST signals for monitoring
```

---

## Quick Diagnostics

### Check Current Signal Distribution
```bash
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT band, COUNT(*) as count,
          ROUND(AVG(final_confidence), 4) as avg_conf,
          ROUND(MIN(final_confidence), 4) as min_conf,
          ROUND(MAX(final_confidence), 4) as max_conf
   FROM eva_confidence_v1
   WHERE computed_at > NOW() - INTERVAL '7 days'
   GROUP BY band
   ORDER BY avg_conf DESC;"
```

### Identify Borderline Signals
```bash
# Signals just below HIGH threshold (candidates for lowering threshold)
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT brand, tag, final_confidence, spread_score, intent_score
   FROM eva_confidence_v1
   WHERE band = 'WATCHLIST'
     AND final_confidence > 0.55
   ORDER BY final_confidence DESC
   LIMIT 10;"
```

### Check Gate Effectiveness
```bash
# What's blocking most signals?
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT gate_failed_reason, COUNT(*)
   FROM eva_confidence_v1
   WHERE band = 'SUPPRESSED'
     AND gate_failed_reason IS NOT NULL
   GROUP BY gate_failed_reason
   ORDER BY COUNT(*) DESC;"
```

---

## Applying Changes

### Method 1: Environment Variables (Persistent)
Edit `.env` file:
```bash
nano .env
# Add/update threshold variables
docker compose restart eva-worker
```

### Method 2: Docker Compose Override (Persistent)
Edit `docker-compose.yml`:
```yaml
services:
  eva-worker:
    environment:
      - EVA_GATE_SPREAD=0.30
      - EVA_GATE_INTENT=0.55
      - EVA_BAND_HIGH=0.65
```
```bash
docker compose up -d eva-worker
```

### Method 3: One-time Test (Temporary)
```bash
# Test new thresholds without persisting
docker exec -e EVA_GATE_SPREAD=0.30 \
            -e EVA_BAND_HIGH=0.65 \
            eva_worker python3 /app/eva_confidence_v1.py

# Check results
docker exec eva_db psql -U eva -d eva_finance -c \
  "SELECT band, COUNT(*) FROM eva_confidence_v1
   WHERE computed_at > NOW() - INTERVAL '5 minutes'
   GROUP BY band;"
```

---

## Safety Checks

### Before Raising Thresholds
1. ✅ Verify current HIGH signals show market correlation
2. ✅ Check false positive rate is <20%
3. ✅ Ensure sufficient data volume (30+ days for production thresholds)
4. ✅ Document reason for change in git commit

### Before Lowering Thresholds
1. ⚠️  Confirm too few signals (<3 per month)
2. ⚠️  Check if data volume is too low (may need more time)
3. ⚠️  Review sample signals manually - are they high quality?
4. ⚠️  Consider raising BAND_HIGH instead of lowering gates

### Never Do This
- ❌ Lower EVA_GATE_INTENT below 0.40 (risks spam)
- ❌ Lower EVA_GATE_SPREAD below 0.15 (single-subreddit signals unreliable)
- ❌ Raise EVA_BAND_HIGH above 0.90 (mathematically impossible to achieve)
- ❌ Change multiple thresholds simultaneously (hard to debug)

---

## Monitoring Dashboard Queries

Save these for ongoing monitoring:

```sql
-- Weekly signal summary
SELECT
  date_trunc('week', day) as week,
  band,
  COUNT(*) as signals,
  ROUND(AVG(final_confidence), 3) as avg_conf,
  ROUND(AVG(spread_score), 3) as avg_spread,
  ROUND(AVG(intent_score), 3) as avg_intent
FROM eva_confidence_v1
WHERE day > current_date - INTERVAL '30 days'
GROUP BY week, band
ORDER BY week DESC, avg_conf DESC;

-- Top signals this week
SELECT
  brand, tag, day,
  final_confidence,
  spread_score, intent_score, acceleration_score
FROM eva_confidence_v1
WHERE band = 'HIGH'
  AND day > current_date - INTERVAL '7 days'
ORDER BY final_confidence DESC;

-- Threshold effectiveness (what's passing vs failing)
SELECT
  CASE
    WHEN spread_score < 0.25 THEN 'spread_blocked'
    WHEN intent_score < 0.50 THEN 'intent_blocked'
    WHEN suppression_score < 0.40 THEN 'meme_blocked'
    WHEN final_confidence >= 0.60 THEN 'HIGH'
    WHEN final_confidence >= 0.50 THEN 'WATCHLIST'
    ELSE 'low_confidence'
  END as status,
  COUNT(*) as count,
  ROUND(AVG(final_confidence), 3) as avg_conf
FROM eva_confidence_v1
WHERE day > current_date - INTERVAL '7 days'
GROUP BY status
ORDER BY count DESC;
```

---

## Contact & Support

For questions about threshold tuning:
1. Review diagnostic output: `diagnostics.py`
2. Check signal quality: Run dashboard queries above
3. Document findings: Update ROADMAP.md with learnings

**Remember:** Quality over quantity. Better to have 3 excellent signals than 20 mediocre ones.
