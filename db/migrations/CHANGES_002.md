# Migration 002: Hardening Changes Summary

## Files Created

1. `db/migrations/002_add_notification_approval.sql` - Complete migration (idempotent)
2. `db/migrations/n8n_notification_queries.sql` - SQL queries for n8n and manual operations
3. `db/migrations/README_notification_pipeline.md` - Complete documentation
4. `db/migrations/CHANGES_002.md` - This file

## Change 1: Add Missing Uniqueness Constraint

### Location
`002_add_notification_approval.sql` lines 74-84

### Implementation
```sql
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
```

### Result
- **Constraint name**: `recommendation_drafts_signal_event_unique`
- **Column**: `signal_event_id`
- **Idempotent**: Yes (uses `IF NOT EXISTS` check)
- **Cleanup**: Removes pre-existing `recommendation_drafts_signal_event_id_key` to avoid redundancy
- **Guarantees**: Exactly one draft per signal_event, prevents duplicate insertions

---

## Change 2: Tighten "Mark Notified" SQL Guard

### Location
`n8n_notification_queries.sql` lines 38-44

### Before
```sql
UPDATE recommendation_drafts
SET notified_at = NOW()
WHERE id = %(draft_id)s
  AND notified_at IS NULL;
```

### After
```sql
UPDATE recommendation_drafts
SET
  notified_at = NOW(),
  last_notify_error = NULL
WHERE id = %(draft_id)s
  AND notified_at IS NULL
  AND notify_ready = true;  -- NEW GUARD
```

### Changes
1. **Added guard**: `AND notify_ready = true`
2. **Clears error**: `last_notify_error = NULL` on success
3. **Defense-in-depth**: Complements existing CHECK constraint

### Result
- Cannot mark unapproved drafts as notified (even if constraint bypassed)
- Success path clears error message (clean state)
- Prevents accidental state corruption

### n8n Documentation Updated
`README_notification_pipeline.md` section "Node 7: Postgres - Mark Notified" now references tightened query.

---

## Change 3: Make "Attempts >= 5" Policy Explicit

### Location
`002_add_notification_approval.sql` lines 7-14 (header comment block)

### Documentation Added
```sql
-- ============================================================================
-- RETRY POLICY DOCUMENTATION
-- ============================================================================
-- Drafts with notify_attempts >= 5 will no longer be claimed automatically
-- and require manual intervention. To recover:
--   1. Investigate root cause (check last_notify_error)
--   2. Fix underlying issue (ntfy down, network problem, etc.)
--   3. Reset attempts: UPDATE recommendation_drafts SET notify_attempts = 0 WHERE id = X;
--   4. Or re-approve: UPDATE recommendation_drafts SET notify_ready = true WHERE id = X;
```

### Supporting Implementation
- **Claim query filter**: `WHERE notify_attempts < 5` (line 24 of n8n_notification_queries.sql)
- **Index optimization**: `idx_recommendation_drafts_notify_pending` includes filter `notify_attempts < 5` (line 106 of migration)
- **Monitoring query**: "Find drafts stuck after max retries" query added (lines 108-119 of n8n_notification_queries.sql)

### Result
- Policy clearly documented at top of migration file
- Recovery steps provided for operators
- Monitoring query helps identify stuck drafts
- No code changes needed (existing implementation already correct)

---

## Optional Change: NOT Implemented

The optional `notification_dead` boolean column was **NOT implemented** per guidance:
> "do NOT do this optional part if it requires touching multiple codepaths extensively"

**Rationale:**
- Existing implementation already correct (filter via `notify_attempts < 5`)
- Adding column would require:
  - Updating claim query
  - Updating monitoring queries
  - Adding trigger or manual update logic to set flag
  - Testing additional state transitions
- Documentation + existing filter is sufficient
- Can be added later if operational need arises

---

## Migration Safety

### Idempotency Guarantees
1. `CREATE TABLE IF NOT EXISTS` - Safe to re-run
2. `DO $$ IF NOT EXISTS` blocks for constraints - Safe to re-run
3. `CREATE INDEX IF NOT EXISTS` - Safe to re-run

### Rollback Plan
```sql
-- If migration needs to be rolled back (destroys data!)
DROP TABLE IF EXISTS recommendation_drafts CASCADE;
```

**WARNING**: Rollback destroys all draft data. Only use in dev/test environments.

### Verification After Migration
```sql
-- Verify table exists
SELECT COUNT(*) FROM recommendation_drafts;

-- Verify uniqueness constraint
SELECT conname, contype
FROM pg_constraint
WHERE conrelid = 'recommendation_drafts'::regclass
  AND conname = 'recommendation_drafts_signal_event_unique';

-- Verify CHECK constraint
SELECT conname, contype
FROM pg_constraint
WHERE conrelid = 'recommendation_drafts'::regclass
  AND conname = 'chk_notify_requires_approval';

-- Verify indexes
SELECT indexname
FROM pg_indexes
WHERE tablename = 'recommendation_drafts';
```

---

## Summary

### What Changed
- ✅ Added uniqueness constraint (Change 1)
- ✅ Tightened mark-notified guard (Change 2)
- ✅ Documented retry policy explicitly (Change 3)
- ✅ Created comprehensive SQL query file for n8n
- ✅ Created complete documentation

### What Remains Manual
- Run migration: `psql -U eva -d eva_finance < db/migrations/002_add_notification_approval.sql`
- Create n8n workflow using queries from `n8n_notification_queries.sql`
- Configure n8n Postgres credentials
- Test end-to-end flow

### Files to Review
1. `db/migrations/002_add_notification_approval.sql` - Complete migration
2. `db/migrations/n8n_notification_queries.sql` - All SQL queries
3. `db/migrations/README_notification_pipeline.md` - Full documentation

All changes are minimal, surgical, and consistent with existing architecture.
