-- Google Trends Cross-Validation Migration
-- Stores Google Trends search interest data to validate Reddit social signals
-- Reduces false positives by confirming social trends with search behavior

-- ============================================================================
-- GOOGLE TRENDS VALIDATION TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS google_trends_validation (
    id SERIAL PRIMARY KEY,

    -- Brand and timing
    brand TEXT NOT NULL,
    checked_at TIMESTAMPTZ DEFAULT NOW(),

    -- Trends data (normalized 0.00 to 1.00)
    search_interest NUMERIC(5,4),          -- Average search interest (0.0000 to 1.0000)
    trend_direction TEXT CHECK (trend_direction IN ('rising', 'stable', 'falling', 'unknown')),
    regional_interest JSONB,               -- Geographic breakdown (optional)

    -- Validation result
    validates_signal BOOLEAN NOT NULL,     -- Does it support the Reddit signal?
    confidence_boost NUMERIC(6,4),         -- Adjustment to confidence score (-0.1000 to +0.1500)

    -- Metadata
    query_term TEXT NOT NULL,              -- What we searched for (may differ from brand)
    timeframe TEXT NOT NULL,               -- e.g., 'today 3-m'
    raw_data JSONB,                        -- Full pytrends response for debugging

    -- Error tracking
    error_message TEXT,                    -- API failure details if validation failed

    -- Constraints
    CONSTRAINT chk_search_interest_range CHECK (search_interest IS NULL OR (search_interest >= 0.0 AND search_interest <= 1.0)),
    CONSTRAINT chk_confidence_boost_range CHECK (confidence_boost >= -0.1000 AND confidence_boost <= 0.1500),
    CONSTRAINT chk_validates_or_error CHECK (validates_signal = true OR error_message IS NOT NULL OR search_interest IS NOT NULL)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Primary lookup: Find recent validations by brand
CREATE INDEX IF NOT EXISTS idx_trends_brand_date
    ON google_trends_validation(brand, checked_at DESC);

-- Query patterns: Find validations that supported signals
CREATE INDEX IF NOT EXISTS idx_trends_validates
    ON google_trends_validation(validates_signal, checked_at DESC)
    WHERE validates_signal = true;

-- Trend analysis: Find rising/falling trends
CREATE INDEX IF NOT EXISTS idx_trends_direction
    ON google_trends_validation(trend_direction, checked_at DESC)
    WHERE trend_direction IN ('rising', 'falling');

-- ============================================================================
-- VIEWS
-- ============================================================================

-- v_recent_trends_validations: Last 30 days of validations
CREATE OR REPLACE VIEW v_recent_trends_validations AS
SELECT
    brand,
    checked_at,
    search_interest,
    trend_direction,
    validates_signal,
    confidence_boost,
    query_term,
    timeframe,
    error_message
FROM google_trends_validation
WHERE checked_at >= NOW() - INTERVAL '30 days'
ORDER BY checked_at DESC;

-- v_trends_validation_summary: Aggregate validation stats
CREATE OR REPLACE VIEW v_trends_validation_summary AS
SELECT
    COUNT(*) as total_validations,
    SUM(CASE WHEN validates_signal THEN 1 ELSE 0 END) as signals_validated,
    SUM(CASE WHEN NOT validates_signal THEN 1 ELSE 0 END) as signals_rejected,
    ROUND(
        100.0 * SUM(CASE WHEN validates_signal THEN 1 ELSE 0 END)::NUMERIC / NULLIF(COUNT(*), 0),
        2
    ) as validation_rate_pct,
    AVG(CASE WHEN validates_signal THEN confidence_boost ELSE NULL END) as avg_boost_when_validated,
    AVG(CASE WHEN NOT validates_signal THEN confidence_boost ELSE NULL END) as avg_penalty_when_rejected,
    SUM(CASE WHEN trend_direction = 'rising' THEN 1 ELSE 0 END) as rising_trends,
    SUM(CASE WHEN trend_direction = 'stable' THEN 1 ELSE 0 END) as stable_trends,
    SUM(CASE WHEN trend_direction = 'falling' THEN 1 ELSE 0 END) as falling_trends,
    SUM(CASE WHEN error_message IS NOT NULL THEN 1 ELSE 0 END) as api_errors
FROM google_trends_validation
WHERE checked_at >= NOW() - INTERVAL '30 days';

-- v_trends_by_brand: Per-brand validation history
CREATE OR REPLACE VIEW v_trends_by_brand AS
SELECT
    brand,
    COUNT(*) as validation_count,
    MAX(checked_at) as last_checked,
    AVG(search_interest) as avg_search_interest,
    MODE() WITHIN GROUP (ORDER BY trend_direction) as most_common_direction,
    SUM(CASE WHEN validates_signal THEN 1 ELSE 0 END) as times_validated,
    AVG(confidence_boost) as avg_confidence_impact
FROM google_trends_validation
WHERE checked_at >= NOW() - INTERVAL '90 days'
GROUP BY brand
ORDER BY validation_count DESC;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE google_trends_validation IS
'Stores Google Trends search interest data to validate Reddit social signals before generating recommendations';

COMMENT ON COLUMN google_trends_validation.search_interest IS
'Normalized search interest (0.0 to 1.0) representing recent vs historical average';

COMMENT ON COLUMN google_trends_validation.trend_direction IS
'Rising: >20% increase in last 30d vs previous 30d, Falling: <-20% decrease, Stable: between -20% and +20%';

COMMENT ON COLUMN google_trends_validation.confidence_boost IS
'Score adjustment applied to base confidence: rising trends get +boost, falling trends get -penalty, max ±15%';

COMMENT ON COLUMN google_trends_validation.validates_signal IS
'True if Google Trends supports the Reddit signal (rising or stable trend with adequate search interest)';

COMMENT ON VIEW v_trends_validation_summary IS
'Aggregate statistics showing how often Google Trends validates social signals (last 30 days)';

COMMENT ON VIEW v_trends_by_brand IS
'Per-brand validation history showing which brands get validated most often (last 90 days)';
