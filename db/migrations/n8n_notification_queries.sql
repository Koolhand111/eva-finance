-- EVA-Finance n8n Notification Queries
-- Companion to migration 002_add_notification_approval.sql
-- These queries are used by the n8n workflow for notification processing

-- ============================================================================
-- CLAIM APPROVED DRAFTS (n8n Postgres Node #1)
-- ============================================================================
-- Transaction-safe claim using FOR UPDATE SKIP LOCKED
-- Increments notify_attempts immediately to track all attempts
-- Returns claimed rows for downstream processing

WITH claimed AS (
  SELECT id
  FROM recommendation_drafts
  WHERE notify_ready = true
    AND notified_at IS NULL
    AND notify_attempts < 5
  ORDER BY created_at ASC
  LIMIT 10
  FOR UPDATE SKIP LOCKED
)
UPDATE recommendation_drafts rd
SET notify_attempts = notify_attempts + 1
FROM claimed
WHERE rd.id = claimed.id
RETURNING
  rd.id,
  rd.signal_event_id,
  rd.brand,
  rd.tag,
  rd.event_type,
  rd.event_time,
  rd.final_confidence,
  rd.band,
  rd.markdown_path,
  rd.bundle_path,
  rd.notify_attempts;

-- ============================================================================
-- MARK AS NOTIFIED - SUCCESS (n8n Postgres Node #2, success path)
-- ============================================================================
-- Change 2: Tightened guard to also require notify_ready = true
-- Prevents accidental marking of unapproved drafts as notified
--
-- n8n Version (use this in n8n Postgres node):
-- UPDATE recommendation_drafts
-- SET
--   notified_at = NOW(),
--   last_notify_error = NULL
-- WHERE id = {{$json.id}}
--   AND notified_at IS NULL
--   AND notify_ready = true;
--
-- Parameterized version (for testing outside n8n):

UPDATE recommendation_drafts
SET
  notified_at = NOW(),
  last_notify_error = NULL
WHERE id = %(draft_id)s
  AND notified_at IS NULL
  AND notify_ready = true;

-- ============================================================================
-- RECORD NOTIFICATION ERROR (n8n Postgres Node #3, failure path)
-- ============================================================================
-- Records error message for troubleshooting
-- notify_attempts already incremented during claim
--
-- IMPORTANT: Before this node, add a Set node to create error_message field:
--   error_message = {{ $json.statusCode ? ('HTTP ' + $json.statusCode + ': ' + ($json.body?.message || $json.statusMessage || 'unknown')) : ($json.error?.message || 'unknown error') }}
--
-- n8n Version (use this in n8n Postgres node):
-- UPDATE recommendation_drafts
-- SET last_notify_error = {{$json.error_message}}
-- WHERE id = {{$json.id}};
--
-- Parameterized version (for testing outside n8n):

UPDATE recommendation_drafts
SET last_notify_error = %(error_message)s
WHERE id = %(draft_id)s;

-- ============================================================================
-- APPROVAL OPERATIONS (Manual / Admin UI)
-- ============================================================================

-- Approve draft for notification (after human review)
UPDATE recommendation_drafts
SET
  notify_ready = true,
  approved_at = COALESCE(approved_at, NOW()),
  approved_by = COALESCE(approved_by, %(approver_name)s)
WHERE signal_event_id = %(event_id)s
  AND notified_at IS NULL;

-- Revoke approval (only before notification sent)
UPDATE recommendation_drafts
SET
  notify_ready = false,
  approved_at = NULL,
  approved_by = NULL
WHERE signal_event_id = %(event_id)s
  AND notified_at IS NULL;

-- Reset retry attempts (manual recovery after fixing root cause)
UPDATE recommendation_drafts
SET
  notify_attempts = 0,
  last_notify_error = NULL
WHERE signal_event_id = %(event_id)s
  AND notified_at IS NULL;

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Check approval status for a specific draft
SELECT
  signal_event_id,
  brand,
  tag,
  event_type,
  final_confidence,
  band,
  notify_ready,
  approved_at,
  approved_by,
  notified_at,
  notify_attempts,
  last_notify_error,
  markdown_path
FROM recommendation_drafts
WHERE signal_event_id = %(event_id)s;

-- Find drafts stuck after max retries (manual investigation required)
SELECT
  signal_event_id,
  brand,
  tag,
  notify_attempts,
  last_notify_error,
  approved_at,
  created_at
FROM recommendation_drafts
WHERE notify_ready = true
  AND notified_at IS NULL
  AND notify_attempts >= 5
ORDER BY created_at DESC;

-- Find all pending drafts (approved but not notified)
SELECT
  signal_event_id,
  brand,
  tag,
  final_confidence,
  band,
  notify_attempts,
  approved_at,
  created_at
FROM recommendation_drafts
WHERE notify_ready = true
  AND notified_at IS NULL
  AND notify_attempts < 5
ORDER BY created_at ASC;
