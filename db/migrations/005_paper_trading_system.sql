-- Paper Trading System Migration
-- Tracks simulated positions from signal generation through exit
-- Enables forward-looking validation of investment thesis

-- ============================================================================
-- PAPER TRADES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS paper_trades (
    id SERIAL PRIMARY KEY,

    -- Signal tracking
    signal_event_id INTEGER REFERENCES signal_events(id) ON DELETE CASCADE,
    brand TEXT NOT NULL,
    tag TEXT NOT NULL,

    -- Ticker and pricing
    ticker TEXT NOT NULL,
    entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
    entry_price NUMERIC(10,2) NOT NULL,
    current_price NUMERIC(10,2),

    -- Position details
    position_size NUMERIC(10,2) DEFAULT 1000.00,  -- Simulated $1000 per trade
    signal_confidence NUMERIC(5,4),

    -- Exit tracking
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    exit_date DATE,
    exit_price NUMERIC(10,2),
    exit_reason TEXT CHECK (exit_reason IN ('time_exit', 'profit_target', 'stop_loss', 'signal_reversal', 'manual')),

    -- Performance
    return_pct NUMERIC(8,4),  -- e.g., 15.5000 for 15.5%
    return_dollar NUMERIC(10,2),
    days_held INTEGER,

    -- Metadata
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    UNIQUE(signal_event_id),  -- One paper trade per signal event
    CHECK (exit_date IS NULL OR exit_date >= entry_date),
    CHECK (status = 'closed' OR (exit_date IS NULL AND exit_price IS NULL AND exit_reason IS NULL))
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Find open positions quickly
CREATE INDEX IF NOT EXISTS idx_paper_trades_open
    ON paper_trades(id) WHERE status = 'open';

-- Track by entry date
CREATE INDEX IF NOT EXISTS idx_paper_trades_entry_date
    ON paper_trades(entry_date DESC);

-- Track by ticker for price updates
CREATE INDEX IF NOT EXISTS idx_paper_trades_ticker
    ON paper_trades(ticker) WHERE status = 'open';

-- Track by brand/tag for analysis
CREATE INDEX IF NOT EXISTS idx_paper_trades_brand
    ON paper_trades(brand);

CREATE INDEX IF NOT EXISTS idx_paper_trades_tag
    ON paper_trades(tag);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- v_open_positions: Active paper trades needing price updates
CREATE OR REPLACE VIEW v_open_positions AS
SELECT
    pt.id,
    pt.ticker,
    pt.brand,
    pt.tag,
    pt.entry_date,
    pt.entry_price,
    pt.current_price,
    pt.signal_confidence,
    CURRENT_DATE - pt.entry_date AS days_held,
    CASE
        WHEN pt.current_price IS NOT NULL
        THEN ((pt.current_price - pt.entry_price) / pt.entry_price) * 100
        ELSE NULL
    END AS current_return_pct,
    pt.position_size
FROM paper_trades pt
WHERE pt.status = 'open'
ORDER BY pt.entry_date DESC;

-- v_closed_positions: Historical performance
CREATE OR REPLACE VIEW v_closed_positions AS
SELECT
    pt.id,
    pt.ticker,
    pt.brand,
    pt.tag,
    pt.entry_date,
    pt.exit_date,
    pt.days_held,
    pt.entry_price,
    pt.exit_price,
    pt.return_pct,
    pt.return_dollar,
    pt.exit_reason,
    pt.signal_confidence,
    CASE WHEN pt.return_pct > 0 THEN 'win' ELSE 'loss' END AS outcome
FROM paper_trades pt
WHERE pt.status = 'closed'
ORDER BY pt.exit_date DESC;

-- v_paper_trading_performance: Real-time validation metrics
CREATE OR REPLACE VIEW v_paper_trading_performance AS
WITH closed_trades AS (
    SELECT
        COUNT(*) AS total_closed,
        SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) AS winners,
        SUM(CASE WHEN return_pct < 0 THEN 1 ELSE 0 END) AS losers,
        AVG(return_pct) AS avg_return_pct,
        AVG(CASE WHEN return_pct > 0 THEN return_pct ELSE NULL END) AS avg_winner_pct,
        AVG(CASE WHEN return_pct < 0 THEN return_pct ELSE NULL END) AS avg_loser_pct,
        AVG(days_held) AS avg_days_held,
        MAX(return_pct) AS best_return,
        MIN(return_pct) AS worst_return
    FROM paper_trades
    WHERE status = 'closed'
),
open_trades AS (
    SELECT
        COUNT(*) AS total_open,
        AVG((current_price - entry_price) / entry_price * 100) AS avg_unrealized_return,
        SUM(CASE WHEN (current_price - entry_price) / entry_price > 0 THEN 1 ELSE 0 END) AS current_winners,
        SUM(CASE WHEN (current_price - entry_price) / entry_price < 0 THEN 1 ELSE 0 END) AS current_losers
    FROM paper_trades
    WHERE status = 'open' AND current_price IS NOT NULL
)
SELECT
    -- Closed positions
    COALESCE(ct.total_closed, 0) AS total_closed_trades,
    COALESCE(ct.winners, 0) AS winning_trades,
    COALESCE(ct.losers, 0) AS losing_trades,
    CASE
        WHEN COALESCE(ct.total_closed, 0) > 0
        THEN ROUND((ct.winners::NUMERIC / ct.total_closed * 100), 2)
        ELSE NULL
    END AS win_rate_pct,
    ROUND(COALESCE(ct.avg_return_pct, 0), 2) AS avg_return_pct,
    ROUND(COALESCE(ct.avg_winner_pct, 0), 2) AS avg_winner_return_pct,
    ROUND(COALESCE(ct.avg_loser_pct, 0), 2) AS avg_loser_return_pct,
    ROUND(COALESCE(ct.avg_days_held, 0), 1) AS avg_days_held,
    ROUND(COALESCE(ct.best_return, 0), 2) AS best_return_pct,
    ROUND(COALESCE(ct.worst_return, 0), 2) AS worst_return_pct,

    -- Open positions
    COALESCE(ot.total_open, 0) AS open_positions,
    ROUND(COALESCE(ot.avg_unrealized_return, 0), 2) AS avg_unrealized_return_pct,
    COALESCE(ot.current_winners, 0) AS open_winning,
    COALESCE(ot.current_losers, 0) AS open_losing
FROM closed_trades ct
CROSS JOIN open_trades ot;

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Update timestamp on paper_trades changes
CREATE OR REPLACE FUNCTION update_paper_trades_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_paper_trades_updated_at
    BEFORE UPDATE ON paper_trades
    FOR EACH ROW
    EXECUTE FUNCTION update_paper_trades_updated_at();

-- ============================================================================
-- INITIAL DATA / COMMENTS
-- ============================================================================

COMMENT ON TABLE paper_trades IS
'Paper trading positions for forward-looking validation of investment signals';

COMMENT ON COLUMN paper_trades.position_size IS
'Simulated position size in dollars (default $1000 per trade)';

COMMENT ON COLUMN paper_trades.exit_reason IS
'time_exit: Held for 90 days, profit_target: +15%, stop_loss: -10%, signal_reversal: Negative signal emerged';

COMMENT ON VIEW v_paper_trading_performance IS
'Real-time validation metrics showing win rate, average returns, and current open positions';
