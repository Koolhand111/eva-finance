# EVA-Finance Metabase Dashboard Setup Guide

## ✅ Status: Metabase Running

**Access URL:** http://localhost:3000 (or http://10.10.0.210:3000)
**Container:** eva_metabase
**Status:** Running ✅
**Initialization:** Complete (11.1s)

---

## Step 1: Initial Setup ✅ COMPLETE

Metabase is running and accessible. When you first access http://localhost:3000, you'll see the setup wizard.

### Setup Wizard Steps:

1. **Language Selection**
   - Choose: English

2. **Create Admin Account**
   - Email: your-email@example.com
   - Password: [create secure password]
   - First name: Admin
   - Last name: User
   - Company: EVA Finance

   **⚠️ IMPORTANT:** Save these credentials securely!

3. **Add Your Data**
   - Click "I'll add my data later" (we'll do this manually in Step 2)

4. **Usage Data**
   - Choose your preference for anonymous usage statistics

---

## Step 2: Connect EVA Finance Database

### Database Connection Settings:

1. Go to: Settings (⚙️) → Admin settings → Databases → Add database

2. Configure connection:
   ```
   Database type:     PostgreSQL
   Name:              EVA Finance
   Host:              db
   Port:              5432
   Database name:     eva_finance
   Username:          eva
   Password:          eva_password_change_me
   ```

3. Advanced settings (expand):
   - ✅ Enable "Rerun queries for simple explorations"
   - ✅ Enable "Choose when syncs and scans happen"
   - Sync: Daily at 00:00
   - Scan: Weekly on Sunday at 00:00

4. Click "Save"

5. Wait for schema sync (2-3 minutes)

### ✅ Verify Connection:

You should see:
- Green checkmark ✅ next to "EVA Finance"
- Tables appear in database browser:
  - `paper_trades`
  - `signal_events`
  - `eva_confidence_v1`
  - `brand_ticker_mapping`
  - `google_trends_validation`
  - `processed_messages`
  - `raw_messages`
  - And ~120 Metabase system tables

---

## Step 3: Create Questions (SQL Queries)

Create these questions in order. For each:
1. Click "New" → "Question"
2. Click "Native query" (SQL)
3. Select "EVA Finance" database
4. Paste SQL
5. Click "Visualize"
6. Configure visualization
7. Save with given name

### Question 1: Open Positions Summary

**SQL:**
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

**Visualization:** Table
**Save as:** "Open Positions Summary"

---

### Question 2: Portfolio Metrics

**SQL:**
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

**Visualization:** Number (create separate visualizations for each metric)
**Save as:** "Portfolio Metrics"

---

### Question 3: Signal Distribution

**SQL:**
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

**Visualization:** Pie chart
**Settings:**
- X-axis: band
- Y-axis: count
- Display: Show percentages

**Save as:** "Signal Distribution"

---

### Question 4: Position Performance Trend

**SQL:**
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

**Visualization:** Line chart
**Settings:**
- X-axis: date
- Y-axis: return_pct
- Series: brand (creates separate line for each brand)

**Save as:** "Position Performance Trend"

---

### Question 5: Closed Positions Summary

**SQL:**
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

**Visualization:** Table
**Save as:** "Closed Positions Summary"

---

### Question 6: Brand Mapping Coverage

**SQL:**
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

**Visualization:** Number (create separate cards)
**Save as:** "Brand Mapping Coverage"

---

### Question 7: Top Brands by Signal Volume

**SQL:**
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

**Visualization:** Bar chart
**Settings:**
- X-axis: brand
- Y-axis: signal_count

**Save as:** "Top Brands by Signal Volume"

---

### Question 8: Recent Signal Events

**SQL:**
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

**Visualization:** Table
**Save as:** "Recent Signal Events"

---

### Question 9: Phase 0 Success Criteria

**SQL:**
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

**Visualization:** Table
**Save as:** "Phase 0 Success Criteria"

---

### Question 10: Weekly Position Activity

**SQL:**
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

**Visualization:** Line chart
**Save as:** "Weekly Position Activity"

---

## Step 4: Create Main Dashboard

1. Click "New" → "Dashboard"
2. Name: "EVA-Finance: Phase 0 Validation"
3. Description: "Paper trading validation dashboard with real-time position tracking"

### Dashboard Layout:

**Row 1: Key Metrics (Numbers)**
Add these questions as Number visualizations:
- Open Positions (from Question 2)
- Closed Positions (from Question 2)
- Avg Open Return % (from Question 2)
- Total Unrealized P&L (from Question 2)

Make each 1/4 width

**Row 2: Portfolio Detail (Full Width)**
- Add "Open Positions Summary" (Question 1)
- Set to full width

**Row 3: Performance Analysis**
- Left 2/3: "Position Performance Trend" (Question 4)
- Right 1/3: "Signal Distribution" (Question 3)

**Row 4: Signal Analysis**
- Left 1/2: "Top Brands by Signal Volume" (Question 7)
- Right 1/2: "Brand Mapping Coverage" (Question 6) as numbers

**Row 5: Recent Activity**
- Full width: "Recent Signal Events" (Question 8)

**Row 6: Historical (if data exists)**
- Full width: "Closed Positions Summary" (Question 5)

### Dashboard Settings:

1. Click ⚙️ on dashboard
2. Set "Auto-refresh": Every 5 minutes
3. Add filter: Date range (optional)
4. Save dashboard

---

## Step 5: Create GO/NO-GO Tracker Dashboard

1. Click "New" → "Dashboard"
2. Name: "Phase 0: GO/NO-GO Tracker"
3. Description: "Track progress toward Phase 0 validation success criteria"

### Dashboard Layout:

**Row 1: Success Criteria (Full Width)**
- Add "Phase 0 Success Criteria" (Question 9)
- Make prominent with large text

**Row 2: Weekly Trend**
- Add "Weekly Position Activity" (Question 10)
- Full width

**Row 3: Key Metrics**
- Win Rate % (from Question 2)
- Avg Winner Return % (from Question 2)
- Total Closed Trades (from Question 2)

Make each 1/3 width

### Dashboard Settings:

- Auto-refresh: Every 1 hour (less frequent than main dashboard)
- Add text card with explanation:
  ```
  Phase 0 Validation Criteria:
  - ✅ At least 10 closed trades
  - ✅ Win rate ≥50%
  - ✅ Average winner return ≥5%

  Check this dashboard weekly to monitor progress.
  ```

---

## Step 6: Share & Subscribe

### Set Homepage:

1. Go to main dashboard
2. Click ⋯ → "Make this the homepage"
3. Now it appears when you log in

### Email Subscriptions:

1. On dashboard, click 🔔 → "Set up a dashboard subscription"
2. Configure:
   - Frequency: Daily at 8:00 AM
   - Recipients: your-email@example.com
   - Format: PDF attachment
3. Save

---

## Quick Links

Once dashboards are created, bookmark these URLs:

- **Metabase Home:** http://localhost:3000
- **Main Dashboard:** http://localhost:3000/dashboard/1
- **GO/NO-GO Tracker:** http://localhost:3000/dashboard/2
- **Questions Browse:** http://localhost:3000/browse/1

---

## Troubleshooting

### Metabase won't start

```bash
# Check logs
docker logs eva_metabase

# Restart
docker compose restart metabase

# If port 3000 is in use, change port in docker-compose.yml:
ports:
  - "3001:3000"
```

### Database connection fails

```bash
# Verify database is running
docker ps | grep eva_db

# Check database container IP
docker inspect eva_db | grep IPAddress

# Try connecting with IP instead of hostname in Metabase
```

### Questions show no data

```bash
# Verify tables have data
docker exec eva_db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM paper_trades;"

# Verify user has permissions
docker exec eva_db psql -U eva -d eva_finance -c "\dp paper_trades"
```

### Sync issues

1. Go to Admin → Databases → EVA Finance
2. Click "Re-scan field values now"
3. Click "Sync database schema now"

---

## Success Checklist

- [ ] Metabase accessible at http://localhost:3000
- [ ] Admin account created
- [ ] Database connected (green checkmark)
- [ ] 10 questions created
- [ ] Main dashboard created with 6+ visualizations
- [ ] GO/NO-GO dashboard created
- [ ] Auto-refresh enabled (5 min on main)
- [ ] Current data showing (3 open positions)
- [ ] Email subscription configured (optional)

---

## Next Steps

1. **Set browser bookmarks** for quick access
2. **Create mobile-friendly views** (Metabase has responsive design)
3. **Set up alerts** for position P&L thresholds
4. **Export dashboard JSON** for version control
5. **Document decision criteria** for GO/NO-GO

---

## Maintenance

**Weekly:**
- Review Phase 0 GO/NO-GO dashboard
- Check for stale data
- Verify auto-refresh working

**Monthly:**
- Review question performance
- Optimize slow queries
- Archive old data if needed

**As Needed:**
- Add new questions for additional metrics
- Modify visualizations based on needs
- Update success criteria if Phase 0 changes

---

Generated: 2026-01-10
Version: 1.0
Status: Initial Setup Complete ✅
