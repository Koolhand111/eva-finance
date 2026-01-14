# Metabase SQL Queries Reference

Quick copy-paste SQL queries for EVA-Finance Metabase dashboards.

---

## Q1: Open Positions Summary

```sql
SELECT
    brand,
    ticker,
    entry_date,
    CURRENT_DATE - entry_date as days_held,
    ROUND(entry_price::numeric, 2) as entry_price,
    ROUND(current_price::numeric, 2) as current_price,
    ROUND(((current_price - entry_price) / entry_price * 100)::numeric, 2) as return_pct,
    ROUND(((current_price - entry_price) * position_size / entry_price)::numeric, 2) as unrealized_pnl,
    ROUND(position_size::numeric, 2) as position_size,
    ROUND(signal_confidence::numeric, 4) as confidence,
    CASE
        WHEN ((current_price - entry_price) / entry_price * 100) >= 15 THEN '🎯 At Target'
        WHEN ((current_price - entry_price) / entry_price * 100) >= 10 THEN '📈 Strong'
        WHEN ((current_price - entry_price) / entry_price * 100) >= 5 THEN '✅ Good'
        WHEN ((current_price - entry_price) / entry_price * 100) >= 0 THEN '➡️ Flat'
        WHEN ((current_price - entry_price) / entry_price * 100) >= -5 THEN '📉 Down'
        ELSE '🛑 Near Stop'
    END as status
FROM paper_trades
WHERE status = 'open'
ORDER BY return_pct DESC;
```

---

## Q2: Portfolio Metrics

```sql
SELECT
    COUNT(*) FILTER (WHERE status = 'open') as open_positions,
    COUNT(*) FILTER (WHERE status = 'closed') as closed_positions,
    ROUND(AVG(return_pct) FILTER (WHERE status = 'open')::numeric, 2) as avg_open_return,
    ROUND(SUM((current_price - entry_price) * position_size / entry_price)
          FILTER (WHERE status = 'open')::numeric, 2) as total_unrealized_pnl,
    COUNT(*) FILTER (WHERE status = 'closed' AND return_pct > 0) as winners,
    COUNT(*) FILTER (WHERE status = 'closed' AND return_pct < 0) as losers,
    CASE
        WHEN COUNT(*) FILTER (WHERE status = 'closed') > 0
        THEN ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'closed' AND return_pct > 0)::numeric /
                   COUNT(*) FILTER (WHERE status = 'closed'), 1)
        ELSE NULL
    END as win_rate
FROM paper_trades;
```

---

## Q3: Signal Distribution

```sql
SELECT
    details->>'band' as band,
    COUNT(*) as count
FROM eva_confidence_v1
WHERE details->>'band' IS NOT NULL
GROUP BY details->>'band'
ORDER BY
    CASE details->>'band'
        WHEN 'HIGH' THEN 1
        WHEN 'WATCHLIST' THEN 2
        WHEN 'SUPPRESSED' THEN 3
        ELSE 4
    END;
```

---

## Q4: Position Performance Trend

```sql
SELECT
    updated_at::date as date,
    brand,
    ROUND(((current_price - entry_price) / entry_price * 100)::numeric, 2) as return_pct
FROM paper_trades
WHERE status = 'open'
  AND updated_at >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY updated_at;
```

---

## Q5: Closed Positions Summary

```sql
SELECT
    brand,
    ticker,
    entry_date,
    exit_date,
    EXTRACT(DAY FROM (exit_date - entry_date)) as days_held,
    ROUND(return_pct::numeric, 2) as return_pct,
    ROUND(return_dollar::numeric, 2) as pnl,
    exit_reason
FROM paper_trades
WHERE status = 'closed'
ORDER BY exit_date DESC;
```

---

## Q6: Brand Mapping Coverage

```sql
SELECT
    COUNT(*) as total_brands,
    COUNT(*) FILTER (WHERE ticker IS NOT NULL) as mapped,
    COUNT(*) FILTER (WHERE material = true) as investable,
    ROUND(100.0 * COUNT(*) FILTER (WHERE ticker IS NOT NULL)::numeric /
          NULLIF(COUNT(*), 0), 1) as mapped_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE material = true)::numeric /
          NULLIF(COUNT(*), 0), 1) as investable_pct
FROM brand_ticker_mapping;
```

---

## Q7: Top Brands by Signal Volume

```sql
SELECT
    brand,
    COUNT(*) as signal_count
FROM signal_events
WHERE brand IS NOT NULL
  AND created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY brand
HAVING COUNT(*) >= 3
ORDER BY signal_count DESC
LIMIT 15;
```

---

## Q8: Recent Signal Events

```sql
SELECT
    event_type,
    brand,
    tag,
    severity,
    day,
    created_at,
    acknowledged
FROM signal_events
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY created_at DESC
LIMIT 50;
```

---

## Q9: Phase 0 Success Criteria

```sql
WITH metrics AS (
    SELECT
        COUNT(*) FILTER (WHERE status = 'closed') as closed_trades,
        ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'closed' AND return_pct > 0)::numeric /
              NULLIF(COUNT(*) FILTER (WHERE status = 'closed'), 0), 1) as win_rate,
        ROUND(AVG(return_pct) FILTER (WHERE status = 'closed' AND return_pct > 0)::numeric, 2) as avg_winner_return
    FROM paper_trades
)
SELECT
    'Closed Trades' as criterion,
    COALESCE(closed_trades::text, '0') as current_value,
    '≥10' as target,
    CASE
        WHEN closed_trades >= 10 THEN '✅ MET'
        WHEN closed_trades >= 5 THEN '⏳ 50%'
        ELSE '⏳ In Progress'
    END as status
FROM metrics
UNION ALL
SELECT
    'Win Rate %',
    COALESCE(win_rate::text, 'N/A'),
    '≥50%',
    CASE
        WHEN win_rate >= 50 THEN '✅ MET'
        WHEN win_rate IS NULL THEN '⏳ Pending Data'
        WHEN win_rate >= 40 THEN '⚠️ Close'
        ELSE '❌ Below Target'
    END
FROM metrics
UNION ALL
SELECT
    'Avg Winner Return %',
    COALESCE(avg_winner_return::text, 'N/A'),
    '≥5%',
    CASE
        WHEN avg_winner_return >= 5 THEN '✅ MET'
        WHEN avg_winner_return IS NULL THEN '⏳ Pending Data'
        WHEN avg_winner_return >= 3 THEN '⚠️ Close'
        ELSE '❌ Below Target'
    END
FROM metrics;
```

---

## Q10: Weekly Position Activity

```sql
SELECT
    DATE_TRUNC('week', entry_date)::date as week_start,
    COUNT(*) as positions_opened,
    COUNT(*) FILTER (WHERE status = 'closed') as closed_this_week,
    ROUND(AVG(return_pct) FILTER (WHERE status = 'open')::numeric, 2) as avg_open_return
FROM paper_trades
WHERE entry_date >= CURRENT_DATE - INTERVAL '12 weeks'
GROUP BY DATE_TRUNC('week', entry_date)
ORDER BY week_start DESC;
```

---

## Additional Useful Queries

### Daily Signal Activity

```sql
SELECT
    day,
    event_type,
    COUNT(*) as events,
    COUNT(DISTINCT brand) as unique_brands
FROM signal_events
WHERE day >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY day, event_type
ORDER BY day DESC, events DESC;
```

### Position Exit Analysis

```sql
SELECT
    exit_reason,
    COUNT(*) as count,
    ROUND(AVG(return_pct)::numeric, 2) as avg_return,
    ROUND(AVG(EXTRACT(DAY FROM (exit_date - entry_date)))::numeric, 1) as avg_days_held
FROM paper_trades
WHERE status = 'closed'
GROUP BY exit_reason
ORDER BY count DESC;
```

### Signal Confidence Distribution

```sql
SELECT
    CASE
        WHEN (details->>'confidence')::numeric >= 0.7 THEN 'High (≥0.7)'
        WHEN (details->>'confidence')::numeric >= 0.5 THEN 'Medium (0.5-0.7)'
        ELSE 'Low (<0.5)'
    END as confidence_band,
    COUNT(*) as count,
    ROUND(AVG((details->>'confidence')::numeric), 4) as avg_confidence
FROM eva_confidence_v1
WHERE details->>'confidence' IS NOT NULL
GROUP BY confidence_band
ORDER BY avg_confidence DESC;
```

### Brands Needing Ticker Mapping

```sql
SELECT
    s.brand,
    COUNT(*) as signal_count,
    bt.ticker,
    bt.material
FROM signal_events s
LEFT JOIN brand_ticker_mapping bt ON LOWER(TRIM(s.brand)) = LOWER(TRIM(bt.brand))
WHERE s.created_at >= CURRENT_DATE - INTERVAL '30 days'
  AND bt.ticker IS NULL
GROUP BY s.brand, bt.ticker, bt.material
HAVING COUNT(*) >= 3
ORDER BY signal_count DESC
LIMIT 20;
```

---

## Dashboard Filter Parameters

### Date Range Filter

```sql
-- Add to any query to make it filterable by date
WHERE created_at >= {{start_date}}
  AND created_at <= {{end_date}}
```

### Brand Filter

```sql
-- Add to filter by specific brand
WHERE brand = {{brand_name}}
```

### Status Filter (for paper_trades)

```sql
WHERE status = {{status}}  -- 'open' or 'closed'
```

---

Generated: 2026-01-10
