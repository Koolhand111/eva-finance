-- EVA-Finance Notification Approval Schema
-- Migration: 002_add_notification_approval
-- Safe to re-run (idempotent)
-- Adds recommendation_drafts table and human approval gates

-- ============================================================================
-- RETRY POLICY DOCUMENTATION
-- ============================================================================
-- Drafts with notify_attempts >= 5 will no longer be claimed automatically
-- and require manual intervention. To recover:
--   1. Investigate root cause (check last_notify_error)
--   2. Fix underlying issue (ntfy down, network problem, etc.)
--   3. Reset attempts ONLY AFTER fixing root cause:
--        UPDATE recommendation_drafts SET notify_attempts = 0 WHERE id = X;
--   4. Or re-approve: UPDATE recommendation_drafts SET notify_ready = true WHERE id = X;
--
-- WHY: Do not reset attempts as a reflex. If the underlying issue is not fixed,
-- you're just burning retry budget and creating noise. Fix first, reset second.

BEGIN;

-- ============================================================================
-- CREATE TABLE: recommendation_drafts
-- ============================================================================
-- Note: Table may already exist from init.sql or previous migrations
-- We use CREATE IF NOT EXISTS + ALTER TABLE ADD COLUMN IF NOT EXISTS

CREATE TABLE IF NOT EXISTS recommendation_drafts (
  id SERIAL PRIMARY KEY,
  signal_event_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  brand TEXT NOT NULL,
  tag TEXT,
  event_time TIMESTAMPTZ NOT NULL,

  -- Confidence snapshot reference
  confidence_snapshot_id INTEGER,
  confidence_computed_at TIMESTAMPTZ,
  final_confidence NUMERIC(5,4),
  band TEXT,

  -- Artifact paths
  bundle_path TEXT NOT NULL,
  bundle_sha256 TEXT NOT NULL,
  markdown_path TEXT NOT NULL,

  -- Approval and notification tracking (base columns)
  notify_ready BOOLEAN NOT NULL DEFAULT FALSE,
  notified_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add new approval/retry columns if they don't exist
ALTER TABLE recommendation_drafts
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS approved_by TEXT,
  ADD COLUMN IF NOT EXISTS notify_attempts INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_notify_error TEXT;

-- ============================================================================
-- CONSTRAINTS
-- ============================================================================

-- Clean up pre-existing uniqueness constraint (may exist from init.sql)
-- We want exactly one constraint with a predictable name
ALTER TABLE recommendation_drafts
  DROP CONSTRAINT IF EXISTS recommendation_drafts_signal_event_id_key;

-- Change 1: Add uniqueness constraint (one draft per signal_event)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'recommendation_drafts_signal_event_unique'
  ) THEN
    ALTER TABLE recommendation_drafts
      ADD CONSTRAINT recommendation_drafts_signal_event_unique
      UNIQUE (signal_event_id);
  END IF;
END $$;

-- Guardrail: Cannot be notified unless approved
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chk_notify_requires_approval'
  ) THEN
    ALTER TABLE recommendation_drafts
      ADD CONSTRAINT chk_notify_requires_approval
      CHECK (notified_at IS NULL OR notify_ready = true);
  END IF;
END $$;

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Index for n8n polling (approved but not notified, retry budget remaining)
CREATE INDEX IF NOT EXISTS idx_recommendation_drafts_notify_pending
  ON recommendation_drafts(created_at DESC)
  WHERE notify_ready = true AND notified_at IS NULL AND notify_attempts < 5;

-- Audit trail index (troubleshooting failed notifications)
CREATE INDEX IF NOT EXISTS idx_recommendation_drafts_notify_failed
  ON recommendation_drafts(notify_attempts DESC)
  WHERE last_notify_error IS NOT NULL;

-- Foreign key index (optional but recommended for joins)
CREATE INDEX IF NOT EXISTS idx_recommendation_drafts_signal_event_id
  ON recommendation_drafts(signal_event_id);

COMMIT;
