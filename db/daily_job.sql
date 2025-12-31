-- EVA Daily Signal Job
-- Runs once per day

-- 1) TAG_ELEVATED events
INSERT INTO signal_events (event_type, tag, day, severity, payload)
SELECT
  'TAG_ELEVATED',
  tag,
  current_date,
  'warning',
  jsonb_build_object('confidence', confidence)
FROM behavior_states
WHERE state = 'ELEVATED'
  AND last_seen = current_date
  AND NOT EXISTS (
    SELECT 1 FROM signal_events
    WHERE event_type = 'TAG_ELEVATED'
      AND tag = behavior_states.tag
      AND day = current_date
  );

-- 2) BRAND_DIVERGENCE events
INSERT INTO signal_events (event_type, brand, day, severity, payload)
SELECT
  'BRAND_DIVERGENCE',
  brand,
  day,
  CASE WHEN abs(z_score) >= 2 THEN 'critical' ELSE 'warning' END,
  jsonb_build_object('z_score', z_score, 'net_flow', net_flow)
FROM v_trigger_brand_divergence
WHERE day = current_date
  AND NOT EXISTS (
    SELECT 1 FROM signal_events
    WHERE event_type = 'BRAND_DIVERGENCE'
      AND brand = v_trigger_brand_divergence.brand
      AND day = current_date
  );
