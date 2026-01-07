-- Add AI approval tracking fields to recommendation_drafts

ALTER TABLE recommendation_drafts
ADD COLUMN IF NOT EXISTS approval_method VARCHAR(20) DEFAULT 'ai',
ADD COLUMN IF NOT EXISTS approval_reasoning TEXT,
ADD COLUMN IF NOT EXISTS approval_confidence NUMERIC(4,3),
ADD COLUMN IF NOT EXISTS approval_completed_at TIMESTAMPTZ;

-- Add index for querying approved recommendations
CREATE INDEX IF NOT EXISTS idx_recommendation_drafts_approved
ON recommendation_drafts(notify_ready, notified_at)
WHERE notify_ready = true AND notified_at IS NULL;

COMMENT ON COLUMN recommendation_drafts.approval_method IS 'Method used for approval: ai, human, auto';
COMMENT ON COLUMN recommendation_drafts.approval_reasoning IS 'AI or human reasoning for approval decision';
COMMENT ON COLUMN recommendation_drafts.approval_confidence IS 'AI confidence in approval decision (0-1)';
COMMENT ON COLUMN recommendation_drafts.approval_completed_at IS 'When approval evaluation completed';
