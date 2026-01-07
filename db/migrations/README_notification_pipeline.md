# EVA-Finance Notification Pipeline Implementation

## Overview

This directory contains the database migration and SQL queries for the human-gated approval → notification pipeline.

## Files

- `002_add_notification_approval.sql` - Idempotent migration (creates recommendation_drafts table, constraints, indexes)
- `n8n_notification_queries.sql` - SQL queries for n8n workflow nodes and manual operations
- `README_notification_pipeline.md` - This file

## Changes Implemented

### Change 1: Uniqueness Constraint
**File:** `002_add_notification_approval.sql` (lines 74-84)

Added `recommendation_drafts_signal_event_unique` constraint to guarantee one draft per signal_event_id.

**Implementation:**
```sql
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

**Guarantees:**
- No duplicate drafts per eligible event
- reco_runner.py INSERT uses ON CONFLICT (signal_event_id) DO NOTHING
- Idempotent (safe to re-run migration)

### Change 2: Tightened "Mark Notified" Guard
**File:** `n8n_notification_queries.sql` (lines 38-44)

Changed success marking to also require `notify_ready = true`.

**Before:**
```sql
UPDATE recommendation_drafts
SET notified_at = NOW()
WHERE id = %(draft_id)s
  AND notified_at IS NULL;
```

**After:**
```sql
UPDATE recommendation_drafts
SET notified_at = NOW(),
    last_notify_error = NULL
WHERE id = %(draft_id)s
  AND notified_at IS NULL
  AND notify_ready = true;  -- NEW: prevents marking unapproved drafts
```

**Guarantees:**
- Cannot mark unapproved drafts as notified (defense-in-depth)
- Complements CHECK constraint `chk_notify_requires_approval`
- Clears error message on success

### Change 3: Explicit Retry Policy
**File:** `002_add_notification_approval.sql` (lines 7-14)

Added documentation block at top of migration file stating retry policy.

**Policy:**
- Drafts with `notify_attempts >= 5` are excluded from automatic claim
- Manual intervention required (see recovery steps in migration file header)
- Claim query filters: `WHERE notify_attempts < 5`
- Index optimized for this filter: `idx_recommendation_drafts_notify_pending`

**Recovery Steps (documented in migration):**
1. Investigate root cause (check `last_notify_error`)
2. Fix underlying issue (ntfy down, network problem, etc.)
3. Reset attempts: `UPDATE recommendation_drafts SET notify_attempts = 0 WHERE id = X;`
4. Or re-approve: `UPDATE recommendation_drafts SET notify_ready = true WHERE id = X;`

## Running the Migration

```bash
# From project root
docker exec -it eva_db psql -U eva -d eva_finance -f /docker-entrypoint-initdb.d/migrations/002_add_notification_approval.sql

# Or if mounted differently
psql -U eva -d eva_finance < db/migrations/002_add_notification_approval.sql
```

## n8n Workflow Node Mapping

### Node 1: Cron Trigger
- Schedule: `*/5 * * * *` (every 5 minutes)
- Timezone: UTC

### Node 2: Postgres - Claim Approved Drafts
- Query: See `n8n_notification_queries.sql` lines 15-36
- Returns: Array of claimed drafts (max 10)

### Node 3: IF - Check Rows Returned
- Condition: `{{ $json.length > 0 }}`

### Node 4: Loop Over Items
- Iterate over claimed drafts

### Node 5: HTTP - Send to ntfy
- Method: POST
- URL: `http://ntfy:80/eva-finance-recommendations`
- **Continue On Fail: true** (critical for error handling)
- Body:
  ```json
  {
    "topic": "eva-finance-recommendations",
    "title": "EVA Signal: {{ $json.brand }}",
    "message": "Tag: {{ $json.tag }}\nConfidence: {{ $json.final_confidence }} ({{ $json.band }})\nEvent: {{ $json.event_time }}\n\nReview recommendation for details.",
    "priority": "default",
    "tags": ["chart_with_upwards_trend"],
    "click": "http://localhost:3000/dashboard/eva-recommendations?event_id={{ $json.signal_event_id }}"
  }
  ```

### Node 6: Set - Create Error Message Field
- **Runs after Node 5** (connect to HTTP node output)
- Field: `error_message`
- Expression:
  ```javascript
  {{ $json.statusCode ? ('HTTP ' + $json.statusCode + ': ' + ($json.body?.message || $json.statusMessage || 'unknown')) : ($json.error?.message || 'unknown error') }}
  ```
- Purpose: Normalizes HTTP error into clean string for database

### Node 7: Switch - Success or Error
- Expression: `{{ $json.statusCode }}`
- Route 200 → Node 8 (Mark Notified)
- Default → Node 9 (Record Error)

### Node 8: Postgres - Mark Notified (Success)
- Query: See `n8n_notification_queries.sql` lines 45-52 (n8n version)
- **Exact SQL:**
  ```sql
  UPDATE recommendation_drafts
  SET
    notified_at = NOW(),
    last_notify_error = NULL
  WHERE id = {{$json.id}}
    AND notified_at IS NULL
    AND notify_ready = true;
  ```
- No parameters needed (uses n8n expressions)

### Node 9: Postgres - Record Error (Failure)
- Query: See `n8n_notification_queries.sql` lines 73-76 (n8n version)
- **Exact SQL:**
  ```sql
  UPDATE recommendation_drafts
  SET last_notify_error = {{$json.error_message}}
  WHERE id = {{$json.id}};
  ```
- Requires Node 6 (Set) to have created `error_message` field

## Manual Operations

All manual SQL operations are documented in `n8n_notification_queries.sql` under the "APPROVAL OPERATIONS" and "MONITORING QUERIES" sections.

**Common tasks:**
- Approve draft: Lines 60-66
- Revoke approval: Lines 69-74
- Reset retry attempts: Lines 77-81
- Check draft status: Lines 89-105
- Find stuck drafts: Lines 108-119

## Testing

See the test plan in the original implementation guidance or run:

```sql
-- Insert test event
INSERT INTO signal_events (event_type, brand, tag, day, severity, payload)
VALUES ('RECOMMENDATION_ELIGIBLE', 'TestBrand', 'test-signal', CURRENT_DATE, 'info', '{"test": true}'::jsonb)
RETURNING id;

-- Run generator (creates draft)
-- docker exec eva_worker python3 -m eva_worker.reco_runner

-- Approve
UPDATE recommendation_drafts
SET notify_ready = true, approved_at = NOW(), approved_by = 'test'
WHERE signal_event_id = (SELECT id FROM signal_events WHERE brand = 'TestBrand' LIMIT 1);

-- Trigger n8n workflow and verify notified_at is set

-- Cleanup
DELETE FROM recommendation_drafts WHERE signal_event_id IN (SELECT id FROM signal_events WHERE payload->>'test' = 'true');
DELETE FROM signal_events WHERE payload->>'test' = 'true';
```

## Invariants

1. **One draft per event**: Guaranteed by `recommendation_drafts_signal_event_unique` constraint
2. **No notification without approval**: Guaranteed by `chk_notify_requires_approval` constraint + tightened UPDATE guard
3. **Idempotent notifications**: `notified_at IS NOT NULL` prevents re-notification
4. **Transaction-safe claiming**: `FOR UPDATE SKIP LOCKED` prevents race conditions
5. **Bounded retries**: Drafts stop being claimed after 5 attempts
6. **Audit trail**: All approvals, attempts, and errors recorded with timestamps

## Architecture Notes

- **Human gate enforced**: No auto-approval in code or database
- **Database-level guarantees**: Constraints prevent invalid states
- **Idempotent**: Migration and queries safe to re-run
- **Post-mortem friendly**: Full audit trail (approved_by, approved_at, notified_at, notify_attempts, last_notify_error)
- **Homelab-first**: Uses Docker, Postgres, n8n, ntfy (no cloud services)
