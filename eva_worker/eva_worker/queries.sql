-- EVA-Finance Recommendation Builder Queries
-- Version: v1.0 (templated)
--
-- NOTE:
-- These queries are placeholders and will be adjusted to your exact schema.
-- The generator will:
--   1) Load the anchor event (RECOMMENDATION_ELIGIBLE)
--   2) Load the most recent confidence snapshot as-of the event time
--   3) Load top evidence items in the event window
--
-- We keep queries in a file so changes are explicit, reviewable, and version-controlled.

--------------------------------------------------------------------------------
-- 1) Anchor event (RECOMMENDATION_ELIGIBLE)
-- Params:
--   :event_id
--------------------------------------------------------------------------------
SELECT
  se.id AS signal_event_id,
  se.event_type,
  se.created_at AS event_time,
  COALESCE(se.brand, '') AS brand,
  COALESCE(se.tag, '') AS tag,
  se.severity,
  se.day,
  se.payload
FROM signal_events se
WHERE se.id = %(event_id)s
  AND se.event_type IN ('WATCHLIST_WARM','RECOMMENDATION_ELIGIBLE');
  

-- 2) Confidence snapshot (best available near anchor event_time)
-- Strategy:
--   1) Search within ±2 days of event_time to handle late scoring jobs
--   2) Prefer exact tag match (when tag is non-empty)
--   3) Prefer snapshots computed before/at event_time (not after)
--   4) Select closest in absolute time
-- Params:
--   %(entity_key)s  -> brand
--   %(tag)s         -> tag (may be empty)
--   %(event_time)s  -> anchor event_time (timestamptz)
WITH target AS (
  SELECT
    trim(%(entity_key)s)::text AS brand,
    trim(COALESCE(%(tag)s, ''))::text AS tag,
    %(event_time)s::timestamptz AS event_time
),
candidates AS (
  SELECT
    e.id,
    e.day,
    e.tag,
    e.brand,
    e.acceleration_score,
    e.intent_score,
    e.spread_score,
    e.baseline_score,
    e.suppression_score,
    e.final_confidence,
    e.band,
    e.gate_failed_reason,
    e.scoring_version,
    e.details,
    e.computed_at,
    -- Tag match priority (0 = exact match, 1 = any tag for brand)
    CASE
      WHEN t.tag <> '' AND lower(trim(e.tag)) = lower(t.tag) THEN 0
      ELSE 1
    END AS tag_match_priority,
    -- Time relationship (0 = before/at event, 1 = after event)
    CASE
      WHEN e.computed_at <= t.event_time THEN 0
      ELSE 1
    END AS after_event,
    -- Absolute time distance in seconds
    ABS(EXTRACT(EPOCH FROM (e.computed_at - t.event_time))) AS time_distance_sec
  FROM eva_confidence_v1 e
  JOIN target t
    ON lower(trim(e.brand)) = lower(t.brand)
  WHERE e.computed_at BETWEEN (t.event_time - INTERVAL '2 days')
                          AND (t.event_time + INTERVAL '2 days')
)
SELECT
  id,
  day,
  tag,
  brand,
  acceleration_score,
  intent_score,
  spread_score,
  baseline_score,
  suppression_score,
  final_confidence,
  band,
  gate_failed_reason,
  scoring_version,
  details,
  computed_at
FROM candidates
ORDER BY
  tag_match_priority,   -- Prefer exact tag match
  after_event,          -- Prefer snapshots before/at event time
  time_distance_sec     -- Closest in time wins
LIMIT 1;


--------------------------------------------------------------------------------
-- 3) Evidence items (top N) within window (brand-first)
-- Params:
--   %(entity_key)s   -> brand (string)
--   %(window_start)s -> timestamptz
--   %(window_end)s   -> timestamptz
--   %(limit)s        -> int
SELECT
  pm.id AS processed_message_id,
  rm.id AS raw_message_id,
  rm."timestamp" AS created_at,

  -- Source fields
  rm.source AS source_platform,
  COALESCE(
    rm.meta->>'subreddit',
    rm.meta->>'community',
    rm.meta->>'channel',
    rm.meta->>'source_sub',
    NULL
  ) AS source_subreddit,
  rm.url AS permalink,

  -- Raw
  rm.text AS raw_text,

  -- Processed
  pm.sentiment,
  pm.intent,
  pm.tags,
  pm.brand,
  NULL::float8 AS weight

FROM processed_messages pm
JOIN raw_messages rm ON rm.id = pm.raw_id
WHERE %(entity_key)s = ANY(pm.brand)
  AND rm."timestamp" >= %(window_start)s
  AND rm."timestamp" <= %(window_end)s
ORDER BY
  CASE pm.intent
    WHEN 'action' THEN 0
    WHEN 'purchase' THEN 1
    WHEN 'evaluative' THEN 2
    WHEN 'exploratory' THEN 3
    ELSE 9
  END,
  rm."timestamp" DESC
LIMIT %(limit)s;

