-- Brand-Ticker Mapping Infrastructure Migration
-- Creates the brand_ticker_mapping table and v_unmapped_brands view
-- for automated brand-to-ticker resolution

-- ============================================================================
-- BRAND TICKER MAPPING TABLE
-- ============================================================================

-- Table to store brand-to-ticker mappings
-- Used by paper_trade_entry.py and brand_mapper_service.py
CREATE TABLE IF NOT EXISTS brand_ticker_mapping (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL UNIQUE,
    ticker TEXT,  -- NULL if private/unlisted
    parent_company TEXT,
    material BOOLEAN DEFAULT false,  -- >5% revenue contribution to parent
    exchange TEXT,  -- NYSE, NASDAQ, etc.
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for case-insensitive lookups
CREATE INDEX IF NOT EXISTS idx_brand_ticker_mapping_brand_lower
    ON brand_ticker_mapping(LOWER(TRIM(brand)));

-- Index for finding tradeable brands
CREATE INDEX IF NOT EXISTS idx_brand_ticker_mapping_material
    ON brand_ticker_mapping(ticker) WHERE material = true AND ticker IS NOT NULL;

-- Trigger to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_brand_ticker_mapping_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_brand_ticker_mapping_updated_at ON brand_ticker_mapping;
CREATE TRIGGER trigger_brand_ticker_mapping_updated_at
    BEFORE UPDATE ON brand_ticker_mapping
    FOR EACH ROW
    EXECUTE FUNCTION update_brand_ticker_mapping_updated_at();

-- ============================================================================
-- V_UNMAPPED_BRANDS VIEW
-- ============================================================================

-- Drop existing view to handle schema changes
DROP VIEW IF EXISTS v_unmapped_brands;

-- View showing brands that appear in signals but aren't mapped to tickers
-- Used by brand_research.py --list-unmapped and monitoring dashboards
CREATE VIEW v_unmapped_brands AS
WITH signal_brands AS (
    -- Get all brands from processed_messages
    SELECT DISTINCT
        UNNEST(pm.brand) AS brand,
        DATE(rm.timestamp) AS day,
        pm.id AS pm_id
    FROM processed_messages pm
    JOIN raw_messages rm ON rm.id = pm.raw_id
    WHERE pm.brand != '{}'
),
brand_stats AS (
    -- Aggregate stats for each brand
    SELECT
        sb.brand,
        COUNT(*) AS signal_count,
        COUNT(DISTINCT sb.day) AS active_days,
        MIN(sb.day) AS first_seen,
        MAX(sb.day) AS last_seen
    FROM signal_brands sb
    GROUP BY sb.brand
),
confidence_stats AS (
    -- Get max confidence for each brand from eva_confidence_v1
    SELECT
        brand,
        MAX(final_confidence) AS max_confidence,
        COUNT(*) AS confidence_entries
    FROM eva_confidence_v1
    WHERE final_confidence IS NOT NULL
    GROUP BY brand
)
SELECT
    bs.brand,
    bs.signal_count,
    bs.active_days,
    bs.first_seen,
    bs.last_seen,
    COALESCE(cs.max_confidence, 0) AS max_confidence,
    COALESCE(cs.confidence_entries, 0) AS confidence_entries,
    CASE
        WHEN btm.id IS NULL THEN 'UNMAPPED'
        WHEN btm.ticker IS NULL THEN 'PRIVATE'
        WHEN btm.material = false THEN 'NON-MATERIAL'
        ELSE 'MAPPED'
    END AS mapping_status
FROM brand_stats bs
LEFT JOIN brand_ticker_mapping btm
    ON LOWER(TRIM(btm.brand)) = LOWER(TRIM(bs.brand))
LEFT JOIN confidence_stats cs
    ON LOWER(TRIM(cs.brand)) = LOWER(TRIM(bs.brand))
WHERE btm.id IS NULL  -- Only show truly unmapped brands
   OR btm.ticker IS NULL  -- Or brands marked as private
ORDER BY bs.signal_count DESC, bs.last_seen DESC;

-- ============================================================================
-- V_BRAND_MAPPING_STATS VIEW
-- ============================================================================

-- Drop existing view to handle schema changes
DROP VIEW IF EXISTS v_brand_mapping_stats;

-- View for monitoring brand mapping coverage
CREATE VIEW v_brand_mapping_stats AS
WITH all_signal_brands AS (
    SELECT DISTINCT UNNEST(brand) AS brand
    FROM processed_messages
    WHERE brand != '{}'
),
mapping_status AS (
    SELECT
        asb.brand,
        CASE
            WHEN btm.id IS NULL THEN 'unmapped'
            WHEN btm.ticker IS NULL THEN 'private'
            WHEN btm.material = false THEN 'non_material'
            ELSE 'tradeable'
        END AS status
    FROM all_signal_brands asb
    LEFT JOIN brand_ticker_mapping btm
        ON LOWER(TRIM(btm.brand)) = LOWER(TRIM(asb.brand))
)
SELECT
    status,
    COUNT(*) AS brand_count,
    ROUND(COUNT(*)::NUMERIC / NULLIF(SUM(COUNT(*)) OVER (), 0) * 100, 2) AS percentage
FROM mapping_status
GROUP BY status
ORDER BY brand_count DESC;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE brand_ticker_mapping IS
'Maps brand names to stock tickers for paper trading. material=true means brand >5% of parent revenue.';

COMMENT ON COLUMN brand_ticker_mapping.material IS
'True if brand represents >5% of parent company revenue (i.e., price moves reflect brand performance)';

COMMENT ON COLUMN brand_ticker_mapping.ticker IS
'Stock ticker symbol. NULL if brand is private/unlisted.';

COMMENT ON VIEW v_unmapped_brands IS
'Brands appearing in signals that need ticker mapping research. Used by brand_research.py --list-unmapped';

COMMENT ON VIEW v_brand_mapping_stats IS
'Monitoring view showing coverage of brand-to-ticker mapping effort';
