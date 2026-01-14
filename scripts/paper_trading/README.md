# EVA Finance - Paper Trading System

Automated paper trading system for forward-validation of brand recommendation signals.

## Overview

The paper trading system automatically:
1. **Creates positions** when signals reach RECOMMENDATION_ELIGIBLE status
2. **Updates positions daily** with current market prices
3. **Closes positions** when exit conditions are met

## Components

### 1. Position Entry ([paper_trade_entry.py](paper_trade_entry.py))

Creates paper trading positions for RECOMMENDATION_ELIGIBLE signals.

**How it works:**
- Queries `signal_events` table for RECOMMENDATION_ELIGIBLE signals without paper trades
- Looks up ticker from `brand_ticker_mapping` table
- Only trades brands where `material = true` (publicly traded + >5% revenue contribution)
- Fetches current price via yfinance
- Creates $1,000 position in `paper_trades` table

**Usage:**
```bash
docker exec eva_worker python /home/koolhand/projects/eva-finance/scripts/paper_trading/paper_trade_entry.py
```

**Example output:**
```
Found 12 signals pending paper trade entry
⊘ Skipping wet n wild - not publicly traded or immaterial
✓ Paper trade #2: Duluth (DLTH) @ $2.33 | Signal: 2026-01-07
✓ Paper trade #3: Mac (EL) @ $113.73 | Signal: 2026-01-04
✓ Paper trade #4: Covergirl (COTY) @ $3.19 | Signal: 2026-01-02
Paper trade entry complete: 3 created, 9 skipped
```

### 2. Daily Updater ([paper_trade_updater.py](paper_trade_updater.py))

Updates all open positions with current prices and checks exit conditions.

**Exit Conditions:**
- **Profit Target:** Return >= +15% → Close with `profit_target`
- **Stop Loss:** Return <= -10% → Close with `stop_loss`
- **Time Limit:** Days held >= 90 → Close with `time_exit`

**Updates:**
- `current_price` - Latest market price
- `days_held` - Trading days since entry
- `return_pct` - Percentage return
- `return_dollar` - Dollar return
- `updated_at` - Last update timestamp

**Usage:**
```bash
docker exec eva_worker python /home/koolhand/projects/eva-finance/scripts/paper_trading/paper_trade_updater.py
```

**Example output:**
```
Found 3 open positions
Updated #4 Covergirl (COTY): $3.25 | +1.88% | $+6.05 | 8 days
Updated #3 Mac (EL): $115.20 | +1.29% | $+11.38 | 6 days
🎯 CLOSED #2 Duluth (DLTH): Entry $2.33 → Exit $2.70 | +15.88% (profit_target) | $+158.85 | 45 days
Update complete: 2 updated, 1 closed, 0 skipped
```

## Automation Setup

### Install Cron Jobs

Run the setup script to install automated daily execution:

```bash
cd /home/koolhand/projects/eva-finance/scripts/paper_trading
./setup_cron.sh
```

This installs:
- **Daily Updater:** Weekdays at 4:30 PM ET (after market close)
- **Weekly Entry Check:** Saturdays at 10:00 AM ET

### Manual Cron Installation

If you prefer to install cron jobs manually:

```bash
crontab -e
```

Add:
```cron
# Daily position updater - 4:30 PM ET (21:30 UTC)
30 21 * * 1-5 cd /home/koolhand/projects/eva-finance && docker exec eva_worker python /home/koolhand/projects/eva-finance/scripts/paper_trading/paper_trade_updater.py >> /home/koolhand/projects/eva-finance/logs/paper_trading_updater.log 2>&1

# Weekly paper trade entry check - Saturdays at 10am ET
0 15 * * 6 cd /home/koolhand/projects/eva-finance && docker exec eva_worker python /home/koolhand/projects/eva-finance/scripts/paper_trading/paper_trade_entry.py >> /home/koolhand/projects/eva-finance/logs/paper_trading_entry.log 2>&1
```

### View Logs

```bash
# Daily updater log
tail -f /home/koolhand/projects/eva-finance/logs/paper_trading_updater.log

# Entry script log
tail -f /home/koolhand/projects/eva-finance/logs/paper_trading_entry.log
```

## Database Schema

### paper_trades Table

```sql
CREATE TABLE paper_trades (
    id SERIAL PRIMARY KEY,
    signal_event_id INTEGER REFERENCES signal_events(id),
    brand TEXT NOT NULL,
    tag TEXT NOT NULL,
    ticker TEXT NOT NULL,
    entry_date DATE NOT NULL,
    entry_price NUMERIC(10,2) NOT NULL,
    current_price NUMERIC(10,2),
    position_size NUMERIC(10,2) DEFAULT 1000.00,  -- $1000 per position
    signal_confidence NUMERIC(5,4),
    status TEXT NOT NULL DEFAULT 'open',  -- 'open' or 'closed'
    exit_date DATE,
    exit_price NUMERIC(10,2),
    exit_reason TEXT,  -- 'profit_target', 'stop_loss', 'time_exit', 'manual'
    return_pct NUMERIC(8,4),
    return_dollar NUMERIC(10,2),
    days_held INTEGER,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### brand_ticker_mapping Table

```sql
CREATE TABLE brand_ticker_mapping (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL UNIQUE,
    ticker TEXT,  -- NULL if private/unlisted
    parent_company TEXT,
    material BOOLEAN DEFAULT false,  -- >5% revenue contribution
    exchange TEXT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## Querying Paper Trading Data

### Active Positions
```sql
SELECT
    id,
    brand,
    ticker,
    entry_date,
    entry_price,
    current_price,
    ROUND(return_pct * 100, 2) as return_pct,
    return_dollar,
    days_held
FROM paper_trades
WHERE status = 'open'
ORDER BY entry_date DESC;
```

### Performance Summary
```sql
SELECT
    COUNT(*) as total_trades,
    COUNT(*) FILTER (WHERE status = 'closed') as closed_trades,
    COUNT(*) FILTER (WHERE exit_reason = 'profit_target') as profit_targets,
    COUNT(*) FILTER (WHERE exit_reason = 'stop_loss') as stop_losses,
    AVG(return_pct) FILTER (WHERE status = 'closed') as avg_return_pct,
    SUM(return_dollar) FILTER (WHERE status = 'closed') as total_pnl
FROM paper_trades;
```

### Best/Worst Performers
```sql
-- Best performers
SELECT brand, ticker, entry_date, exit_date,
       ROUND(return_pct * 100, 2) as return_pct, return_dollar
FROM paper_trades
WHERE status = 'closed'
ORDER BY return_pct DESC
LIMIT 10;

-- Worst performers
SELECT brand, ticker, entry_date, exit_date,
       ROUND(return_pct * 100, 2) as return_pct, return_dollar
FROM paper_trades
WHERE status = 'closed'
ORDER BY return_pct ASC
LIMIT 10;
```

## Monitoring

### Check Script Status

```bash
# Check if updater is running
ps aux | grep paper_trade_updater

# View recent cron executions
grep paper_trading /var/log/syslog | tail -20

# Check cron jobs
crontab -l | grep paper_trading
```

### Health Checks

```bash
# Check for positions without recent updates
docker exec eva_db psql -U eva -d eva_finance -c "
SELECT id, brand, ticker, status, updated_at
FROM paper_trades
WHERE status = 'open'
  AND updated_at < NOW() - INTERVAL '2 days'
ORDER BY updated_at;
"

# Check for failed price fetches
tail -100 /home/koolhand/projects/eva-finance/logs/paper_trading_updater.log | grep ERROR
```

## Troubleshooting

### Position not updating?
1. Check if yfinance can fetch the ticker: `docker exec eva_worker python -c "import yfinance as yf; print(yf.Ticker('DLTH').history(period='1d'))"`
2. Check logs for errors: `tail -50 /home/koolhand/projects/eva-finance/logs/paper_trading_updater.log`
3. Verify ticker is correct in brand_ticker_mapping table

### Cron not running?
1. Check cron service: `systemctl status cron`
2. Check cron logs: `grep CRON /var/log/syslog | tail -20`
3. Verify docker containers are running: `docker ps`

### Manual position close
```sql
UPDATE paper_trades
SET
    status = 'closed',
    exit_date = CURRENT_DATE,
    exit_price = current_price,
    exit_reason = 'manual',
    updated_at = NOW()
WHERE id = <position_id>;
```

## Configuration

### Exit Thresholds

Edit [paper_trade_updater.py](paper_trade_updater.py:48-50) to change:
```python
PROFIT_TARGET = 0.15  # 15% gain
STOP_LOSS = -0.10     # -10% loss
MAX_DAYS_HELD = 90    # 90 day time limit
```

### Position Size

Default: $1,000 per position

To change, edit the position_size in [paper_trade_entry.py](paper_trade_entry.py:171)

## Architecture

```
signal_events (RECOMMENDATION_ELIGIBLE)
    ↓
paper_trade_entry.py
    ↓ (looks up ticker)
brand_ticker_mapping (material brands only)
    ↓ (fetches price)
yfinance API
    ↓ (creates $1K position)
paper_trades (status='open')
    ↓ (daily updates)
paper_trade_updater.py
    ↓ (checks exit conditions)
paper_trades (status='closed' if exit triggered)
```

## Support

For issues or questions:
- Check logs: `/home/koolhand/projects/eva-finance/logs/`
- Review database: `docker exec eva_db psql -U eva -d eva_finance`
- Manual run: `docker exec eva_worker python /home/koolhand/projects/eva-finance/scripts/paper_trading/paper_trade_updater.py`
