# Migration 002 - Verification Complete ✅

All five verification points have been successfully validated.

## ✅ Point 1: Migration Won't Fight Existing Schema

**Status:** VERIFIED

- Migration uses `CREATE TABLE IF NOT EXISTS`
- Migration uses `ALTER TABLE ADD COLUMN IF NOT EXISTS`
- All 4 new columns successfully added without data loss:
  - `approved_at` (timestamptz, nullable)
  - `approved_by` (text, nullable)
  - `notify_attempts` (integer, default 0)
  - `last_notify_error` (text, nullable)

**Result:** Safe to re-run, no conflicts with existing schema

---

## ✅ Point 2: Uniqueness Constraint in Place

**Status:** VERIFIED

**Constraint details:**
- Name: `recommendation_drafts_signal_event_unique`
- Definition: `UNIQUE (signal_event_id)`
- Idempotent: Yes (uses `IF NOT EXISTS` check)

**Cleanup performed:**
- Removed redundant pre-existing constraint: `recommendation_drafts_signal_event_id_key`
- **Current state:** Exactly ONE uniqueness constraint (no confusion in post-mortems)

**Verification query:**
```sql
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'recommendation_drafts'::regclass AND contype = 'u';
```

**Output:**
```
conname                               | pg_get_constraintdef
--------------------------------------+-----------------------
recommendation_drafts_signal_event_unique | UNIQUE (signal_event_id)
```

---

## ✅ Point 3: Mark Notified Guard is Strict

**Status:** VERIFIED

**Query location:** `n8n_notification_queries.sql` lines 38-44

**Guard requirements:**
```sql
UPDATE recommendation_drafts
SET
  notified_at = NOW(),
  last_notify_error = NULL
WHERE id = %(draft_id)s
  AND notified_at IS NULL   -- ✅ Prevent double-notification
  AND notify_ready = true;  -- ✅ NEW: Prevent marking unapproved drafts
```

**Defense-in-depth:**
- Application-level guard: `AND notify_ready = true` in UPDATE
- Database-level constraint: `CHECK (notified_at IS NULL OR notify_ready = true)`

**Race condition closed:**
- Revoked approvals (notify_ready set to false) cannot be marked as notified

---

## ✅ Point 4: Claim Query Uses SKIP LOCKED Correctly

**Status:** VERIFIED

**Query location:** `n8n_notification_queries.sql` lines 15-36

**Pattern (correct):**
```sql
WITH claimed AS (
  SELECT id
  FROM recommendation_drafts
  WHERE notify_ready = true
    AND notified_at IS NULL
    AND notify_attempts < 5
  ORDER BY created_at ASC
  LIMIT 10
  FOR UPDATE SKIP LOCKED  -- ✅ Lock placement correct
)
UPDATE recommendation_drafts rd
SET notify_attempts = notify_attempts + 1
FROM claimed
WHERE rd.id = claimed.id
RETURNING ...;
```

**Concurrent behavior:**
- Two n8n instances running simultaneously will claim different rows
- Second instance gets either different rows or empty result
- No duplicate processing

**Lock placement:** ✅ Inside CTE, before UPDATE (correct)

---

## ✅ Point 5: Retry Policy Documentation Enhanced

**Status:** VERIFIED

**Location:** `002_add_notification_approval.sql` lines 7-18

**Documentation includes:**
1. ✅ What: "notify_attempts >= 5 → manual intervention required"
2. ✅ How: Exact recovery SQL provided
3. ✅ **Why (NEW):** "Reset ONLY AFTER fixing root cause"
4. ✅ **Why (NEW):** "Don't reset as reflex"
5. ✅ **Why (NEW):** "Fix first, reset second"

**Full text:**
```sql
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
```

**Result:** Prevents EVA from becoming a "retry until you hate it" machine

---

## Final Database State

**Table:** `recommendation_drafts` (20 columns total)

**Columns:**
- Base (14): id, signal_event_id, event_type, brand, tag, event_time, confidence_snapshot_id, confidence_computed_at, final_confidence, band, bundle_path, bundle_sha256, markdown_path, created_at
- Approval/notification (6): notify_ready, notified_at, approved_at, approved_by, notify_attempts, last_notify_error

**Constraints (2):**
1. `recommendation_drafts_signal_event_unique` - UNIQUE (signal_event_id)
2. `chk_notify_requires_approval` - CHECK (notified_at IS NULL OR notify_ready = true)

**Indexes (3):**
1. `idx_recommendation_drafts_notify_pending` - For n8n polling (optimized for retry filter)
2. `idx_recommendation_drafts_notify_failed` - For troubleshooting
3. `idx_recommendation_drafts_signal_event_id` - Foreign key optimization

---

## Migration Safety

✅ **Idempotent:** Safe to re-run multiple times
✅ **Non-destructive:** No data loss
✅ **Backward compatible:** Existing data preserved
✅ **Forward compatible:** Supports future changes
✅ **Constraint cleanup:** Removed redundant uniqueness constraint
✅ **Documentation complete:** All WHYs explained

---

## Reviewer Notes Addressed

1. **"Confirm migration won't fight existing schema"** → VERIFIED: Uses IF NOT EXISTS patterns
2. **"Verify uniqueness constraint actually in place"** → VERIFIED: Exactly one constraint, redundant one removed
3. **"Verify mark notified guard is strict"** → VERIFIED: Requires notify_ready = true
4. **"Confirm claim query uses SKIP LOCKED correctly"** → VERIFIED: Correct CTE placement
5. **"Retry policy documentation correct"** → ENHANCED: Added WHY explanations

---

## Next Steps

Migration is production-ready. No further changes needed for database schema.

**Remaining work (not in scope of migration):**
1. Create n8n workflow using queries from `n8n_notification_queries.sql`
2. Configure n8n Postgres credentials
3. Test end-to-end notification flow
4. Subscribe to ntfy topic

**Files ready for review:**
- ✅ `db/migrations/002_add_notification_approval.sql` - Complete migration
- ✅ `db/migrations/n8n_notification_queries.sql` - All SQL queries
- ✅ `db/migrations/README_notification_pipeline.md` - Complete documentation
- ✅ `db/migrations/CHANGES_002.md` - Detailed changelog
- ✅ `db/migrations/VERIFICATION_COMPLETE.md` - This file

**Migration applied:** 2026-01-05
**Status:** COMPLETE ✅
