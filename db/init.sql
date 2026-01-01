-- EVA-Finance Database Schema
-- Creates all tables, views, and indexes needed by eva-api and eva-worker

-- ============================================================================
-- TABLES
-- ============================================================================

-- Raw incoming messages from external sources
CREATE TABLE IF NOT EXISTS raw_messages (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    platform_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    text TEXT NOT NULL,
    url TEXT,
    meta JSONB DEFAULT '{}'::jsonb,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Processed/extracted message data from LLM or fallback
CREATE TABLE IF NOT EXISTS processed_messages (
    id SERIAL PRIMARY KEY,
    raw_id INTEGER NOT NULL REFERENCES raw_messages(id) ON DELETE CASCADE,
    brand TEXT[] DEFAULT '{}',
    product TEXT[] DEFAULT '{}',
    category TEXT[] DEFAULT '{}',
    sentiment TEXT,
    intent TEXT,
    tickers TEXT[] DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    processor_version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Signal events emitted by triggers and scoring
CREATE TABLE IF NOT EXISTS signal_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    tag TEXT,
    brand TEXT,
    day DATE NOT NULL DEFAULT CURRENT_DATE,
    severity TEXT NOT NULL DEFAULT 'warning',
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    acknowledged BOOLEAN DEFAULT FALSE
);

-- Behavioral state tracking for tags (ELEVATED, NORMAL, etc.)
CREATE TABLE IF NOT EXISTS behavior_states (
    id SERIAL PRIMARY KEY,
    tag TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'NORMAL',
    confidence NUMERIC(5,4) DEFAULT 0.0,
    first_seen DATE NOT NULL DEFAULT CURRENT_DATE,
    last_seen DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tag)
);

-- Confidence scores computed by eva_confidence_v1.py
CREATE TABLE IF NOT EXISTS eva_confidence_v1 (
    id SERIAL PRIMARY KEY,
    day DATE NOT NULL,
    tag TEXT NOT NULL,
    brand TEXT NOT NULL,
    acceleration_score NUMERIC(5,4),
    intent_score NUMERIC(5,4),
    spread_score NUMERIC(5,4),
    baseline_score NUMERIC(5,4),
    suppression_score NUMERIC(5,4),
    final_confidence NUMERIC(5,4),
    band TEXT,
    gate_failed_reason TEXT,
    scoring_version TEXT NOT NULL DEFAULT 'v1',
    details JSONB DEFAULT '{}'::jsonb,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(day, tag, brand, scoring_version)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- raw_messages: speed up unprocessed batch queries
CREATE INDEX IF NOT EXISTS idx_raw_messages_unprocessed
    ON raw_messages(id) WHERE processed = FALSE;

CREATE INDEX IF NOT EXISTS idx_raw_messages_timestamp
    ON raw_messages(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_raw_messages_source
    ON raw_messages(source);

-- processed_messages: support joins and tag/brand queries
CREATE INDEX IF NOT EXISTS idx_processed_messages_raw_id
    ON processed_messages(raw_id);

CREATE INDEX IF NOT EXISTS idx_processed_messages_created_at
    ON processed_messages(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_processed_messages_brand
    ON processed_messages USING GIN(brand);

CREATE INDEX IF NOT EXISTS idx_processed_messages_tags
    ON processed_messages USING GIN(tags);

-- signal_events: deduplication and queries
CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_events_dedup
    ON signal_events(event_type, COALESCE(tag, ''), COALESCE(brand, ''), day);

CREATE INDEX IF NOT EXISTS idx_signal_events_unacked
    ON signal_events(id DESC) WHERE acknowledged = FALSE;

CREATE INDEX IF NOT EXISTS idx_signal_events_day
    ON signal_events(day DESC);

-- behavior_states: tag lookups
CREATE INDEX IF NOT EXISTS idx_behavior_states_state
    ON behavior_states(state) WHERE state = 'ELEVATED';

-- eva_confidence_v1: band queries
CREATE INDEX IF NOT EXISTS idx_eva_confidence_band
    ON eva_confidence_v1(band, day DESC);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- v_trigger_tag_elevated: Tags currently in ELEVATED state
-- Used by: worker.py emit_trigger_events()
CREATE OR REPLACE VIEW v_trigger_tag_elevated AS
SELECT
    tag,
    last_seen AS day,
    confidence
FROM behavior_states
WHERE state = 'ELEVATED'
  AND last_seen >= CURRENT_DATE - INTERVAL '1 day';

-- v_daily_brand_tag_stats: Daily aggregated stats per brand+tag combo
-- Helper view for computing deltas and candidate signals
CREATE OR REPLACE VIEW v_daily_brand_tag_stats AS
SELECT
    DATE(rm.timestamp) AS day,
    UNNEST(pm.brand) AS brand,
    UNNEST(pm.tags) AS tag,
    rm.source,
    pm.intent,
    pm.sentiment,
    COUNT(*) AS msg_count
FROM processed_messages pm
JOIN raw_messages rm ON rm.id = pm.raw_id
WHERE pm.brand != '{}'
  AND pm.tags != '{}'
GROUP BY DATE(rm.timestamp), UNNEST(pm.brand), UNNEST(pm.tags), rm.source, pm.intent, pm.sentiment;

-- v_brand_tag_daily_summary: Summarized daily metrics per brand+tag
CREATE OR REPLACE VIEW v_brand_tag_daily_summary AS
SELECT
    day,
    brand,
    tag,
    SUM(msg_count) AS msg_count,
    COUNT(DISTINCT source) AS source_count,
    SUM(CASE WHEN intent IN ('buy', 'own', 'recommendation') THEN msg_count ELSE 0 END)::NUMERIC
        / NULLIF(SUM(msg_count), 0) AS action_intent_rate,
    SUM(CASE WHEN sentiment IN ('strong_positive', 'strong_negative') THEN msg_count ELSE 0 END)::NUMERIC
        / NULLIF(SUM(msg_count), 0) AS eval_intent_rate
FROM v_daily_brand_tag_stats
GROUP BY day, brand, tag;

-- v_trigger_brand_divergence: Brands with significant share-of-voice change
-- Used by: worker.py emit_trigger_events()
CREATE OR REPLACE VIEW v_trigger_brand_divergence AS
WITH daily_totals AS (
    SELECT
        day,
        tag,
        SUM(msg_count) AS total_msgs
    FROM v_brand_tag_daily_summary
    GROUP BY day, tag
),
brand_share AS (
    SELECT
        s.day,
        s.tag,
        s.brand,
        s.msg_count,
        s.msg_count::NUMERIC / NULLIF(dt.total_msgs, 0) AS share
    FROM v_brand_tag_daily_summary s
    JOIN daily_totals dt ON dt.day = s.day AND dt.tag = s.tag
),
share_delta AS (
    SELECT
        t.tag AS tag_name,
        t.brand AS brand_name,
        t.day,
        t.share AS today_share,
        COALESCE(y.share, 0) AS yesterday_share,
        (t.share - COALESCE(y.share, 0)) * 100 AS delta_pct
    FROM brand_share t
    LEFT JOIN brand_share y
        ON y.tag = t.tag
        AND y.brand = t.brand
        AND y.day = t.day - INTERVAL '1 day'
    WHERE t.day >= CURRENT_DATE - INTERVAL '7 days'
)
SELECT tag_name, brand_name, day, delta_pct
FROM share_delta
WHERE ABS(delta_pct) >= 5.0;  -- Only significant moves

-- v_eva_candidate_brand_signals_v1: Candidate signals for confidence scoring
-- Used by: eva_confidence_v1.py main()
CREATE OR REPLACE VIEW v_eva_candidate_brand_signals_v1 AS
WITH base_stats AS (
    SELECT
        DATE(rm.timestamp) AS day,
        UNNEST(pm.brand) AS brand,
        UNNEST(pm.tags) AS tag,
        rm.source,
        rm.platform_id,
        pm.intent,
        pm.sentiment
    FROM processed_messages pm
    JOIN raw_messages rm ON rm.id = pm.raw_id
    WHERE pm.brand != '{}'
      AND pm.tags != '{}'
),
daily_agg AS (
    SELECT
        day,
        brand,
        tag,
        COUNT(*) AS msg_count,
        COUNT(DISTINCT source) AS source_count,
        COUNT(DISTINCT COALESCE(platform_id, source)) AS platform_count,
        SUM(CASE WHEN intent IN ('buy', 'own', 'recommendation') THEN 1 ELSE 0 END)::NUMERIC
            / NULLIF(COUNT(*), 0) AS action_intent_rate,
        SUM(CASE WHEN sentiment IN ('strong_positive', 'strong_negative') THEN 1 ELSE 0 END)::NUMERIC
            / NULLIF(COUNT(*), 0) AS eval_intent_rate
    FROM base_stats
    GROUP BY day, brand, tag
),
with_delta AS (
    SELECT
        t.day,
        t.brand,
        t.tag,
        t.msg_count,
        t.source_count,
        t.platform_count,
        t.action_intent_rate,
        t.eval_intent_rate,
        -- Delta: compare today's msg share to yesterday's
        CASE
            WHEN COALESCE(y.msg_count, 0) = 0 THEN 0.5  -- new signal, moderate delta
            ELSE (t.msg_count - y.msg_count)::NUMERIC / y.msg_count
        END AS delta_pct,
        -- Meme risk: high eval rate + low action rate suggests noise
        CASE
            WHEN t.action_intent_rate < 0.1 AND t.eval_intent_rate > 0.5 THEN 0.7
            WHEN t.action_intent_rate < 0.2 AND t.eval_intent_rate > 0.3 THEN 0.4
            ELSE 0.1
        END AS meme_risk
    FROM daily_agg t
    LEFT JOIN daily_agg y
        ON y.brand = t.brand
        AND y.tag = t.tag
        AND y.day = t.day - INTERVAL '1 day'
)
SELECT
    day,
    tag,
    brand,
    delta_pct,
    msg_count,
    source_count,
    platform_count,
    action_intent_rate,
    eval_intent_rate,
    meme_risk
FROM with_delta
WHERE msg_count >= 2;  -- Minimum threshold for signal consideration

-- ============================================================================
-- FUNCTIONS (optional helpers)
-- ============================================================================

-- Function to update behavior_states when tags reach thresholds
CREATE OR REPLACE FUNCTION update_behavior_state(
    p_tag TEXT,
    p_confidence NUMERIC
) RETURNS VOID AS $$
BEGIN
    INSERT INTO behavior_states (tag, state, confidence, first_seen, last_seen)
    VALUES (
        p_tag,
        CASE WHEN p_confidence >= 0.7 THEN 'ELEVATED' ELSE 'NORMAL' END,
        p_confidence,
        CURRENT_DATE,
        CURRENT_DATE
    )
    ON CONFLICT (tag) DO UPDATE SET
        state = CASE WHEN p_confidence >= 0.7 THEN 'ELEVATED' ELSE behavior_states.state END,
        confidence = p_confidence,
        last_seen = CURRENT_DATE,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;
