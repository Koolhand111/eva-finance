-- Schema Patch: Add UNIQUE constraint for backfill deduplication
-- Apply this before running reddit_historical_backfill.py

-- Add unique constraint on (source, platform_id) if not exists
-- This prevents duplicate inserts during backfill
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'raw_messages_source_platform_id_key'
    ) THEN
        ALTER TABLE raw_messages
        ADD CONSTRAINT raw_messages_source_platform_id_key
        UNIQUE (source, platform_id);

        RAISE NOTICE 'Added UNIQUE constraint on (source, platform_id)';
    ELSE
        RAISE NOTICE 'UNIQUE constraint already exists';
    END IF;
END$$;

-- Optional: Add index for faster backfill inserts
CREATE INDEX IF NOT EXISTS idx_raw_messages_source_platform
    ON raw_messages(source, platform_id);
