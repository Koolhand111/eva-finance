# n8n Notification Workflow - Quick Reference

## Workflow Structure

```
[Cron: */5 * * * *]
    ↓
[Postgres: Claim Drafts]
    ↓
[IF: Rows exist?]
    ↓ true
[Loop: Iterate drafts]
    ↓
[HTTP: Send to ntfy] (Continue On Fail = true)
    ↓
[Set: Normalize error] (always runs)
    ↓
[Switch: Success or Error?]
    ↓ 200          ↓ default
[Postgres: Mark]  [Postgres: Record Error]
```

---

## Node 1: Cron Trigger
- **Schedule:** `*/5 * * * *` (every 5 minutes)
- **Timezone:** UTC

---

## Node 2: Postgres - Claim Approved Drafts
- **Operation:** Execute Query
- **Query:**
```sql
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
```
- **Output:** Array of claimed drafts (max 10)

---

## Node 3: IF - Check Rows Returned
- **Condition:** `{{ $json.length > 0 }}`
- **True:** Continue to Loop
- **False:** Stop workflow (no pending drafts)

---

## Node 4: Loop Over Items
- **Mode:** Loop
- **Expression:** `{{ $json }}`
- Iterates over each claimed draft

---

## Node 5: HTTP - Send to ntfy
- **Method:** POST
- **URL:** `http://ntfy:80/eva-finance-recommendations`
- **Headers:**
  - `Content-Type: application/json`
- **Body:**
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
- **Continue On Fail:** ✅ **true** (CRITICAL)
- **Timeout:** 10000ms

---

## Node 6: Set - Create Error Message Field
- **Field Name:** `error_message`
- **Expression:**
```javascript
{{ $json.statusCode ? ('HTTP ' + $json.statusCode + ': ' + ($json.body?.message || $json.statusMessage || 'unknown')) : ($json.error?.message || 'unknown error') }}
```
- **Purpose:** Normalizes HTTP response/error into clean database-safe string
- **Runs:** Always (after Node 5, regardless of success/failure)

---

## Node 7: Switch - Success or Error
- **Expression:** `{{ $json.statusCode }}`
- **Routes:**
  - Route 0: Value = `200` → Go to Node 8 (Mark Notified)
  - Default (fallback): → Go to Node 9 (Record Error)

---

## Node 8: Postgres - Mark Notified (Success Path)
- **Operation:** Execute Query
- **Query:**
```sql
UPDATE recommendation_drafts
SET
  notified_at = NOW(),
  last_notify_error = NULL
WHERE id = {{$json.id}}
  AND notified_at IS NULL
  AND notify_ready = true;
```
- **No parameters** (uses n8n expressions)
- **Guards:**
  - `notified_at IS NULL` - Prevents double-notification
  - `notify_ready = true` - Prevents marking revoked approvals

---

## Node 9: Postgres - Record Error (Failure Path)
- **Operation:** Execute Query
- **Query:**
```sql
UPDATE recommendation_drafts
SET last_notify_error = {{$json.error_message}}
WHERE id = {{$json.id}};
```
- **No parameters** (uses n8n expressions)
- **Depends on:** Node 6 creating `error_message` field

---

## Key Design Decisions

### ✅ Node #1 (Claim) - Keep Exactly As-Is
- `FOR UPDATE SKIP LOCKED` is in correct place (inside CTE)
- Increments `notify_attempts` immediately
- Returns everything downstream needs
- **No changes needed**

### ✅ Node #2 (Success) - n8n-Safe SQL
- Uses `{{$json.id}}` (present because Node 1 returns `rd.id`)
- Guards prevent "revoked approval" race
- Still idempotent (`notified_at IS NULL`)

### ✅ Node #3 (Failure) - Requires Set Node
- HTTP error object not always where you expect in n8n
- Set node normalizes error into predictable field
- Prevents database errors from malformed error strings

### 🔒 Continue On Fail = true
- **Critical setting** on HTTP node
- Without it, workflow stops on ntfy failure
- With it, error path can record the failure

---

## Testing Checklist

1. ✅ Two n8n instances running simultaneously claim different rows
2. ✅ HTTP 200 triggers Mark Notified
3. ✅ HTTP ≠ 200 triggers Record Error
4. ✅ `notified_at` set after success
5. ✅ `last_notify_error` set after failure
6. ✅ Re-running workflow does NOT re-notify (idempotent)
7. ✅ Drafts with `notify_attempts >= 5` stop being claimed
8. ✅ Revoked approvals (`notify_ready = false`) cannot be marked as notified

---

## Common Mistakes to Avoid

❌ **Don't use parameterized queries in n8n Postgres nodes**
- Use: `WHERE id = {{$json.id}}`
- Not: `WHERE id = %(draft_id)s`

❌ **Don't forget Continue On Fail on HTTP node**
- Without it, error path never runs
- Failures become silent (attempts increment but no error recorded)

❌ **Don't skip the Set node**
- HTTP error structure varies (statusCode vs error.message vs response.body)
- Set node normalizes all cases into clean `error_message` field

❌ **Don't put FOR UPDATE outside the CTE**
- Correct: `WITH claimed AS (SELECT ... FOR UPDATE SKIP LOCKED)`
- Wrong: `WITH claimed AS (SELECT ...) FOR UPDATE SKIP LOCKED`

---

## Manual Operations

See `n8n_notification_queries.sql` for:
- Approve draft (after human review)
- Revoke approval (before notification)
- Reset retry attempts (after fixing root cause)
- Find stuck drafts (attempts >= 5)
- Check draft status

---

## Recovery After Failures

If drafts get stuck (notify_attempts >= 5):

1. **Investigate:** `SELECT last_notify_error FROM recommendation_drafts WHERE id = X;`
2. **Fix root cause** (ntfy down, network issue, etc.)
3. **Reset attempts:** `UPDATE recommendation_drafts SET notify_attempts = 0 WHERE id = X;`
4. **Verify fix:** Wait for next cron run (5 min), check if notification succeeds

**DO NOT** reset attempts as a reflex. Fix first, reset second.

---

## Files Reference

- **Migration:** `db/migrations/002_add_notification_approval.sql`
- **Queries:** `db/migrations/n8n_notification_queries.sql`
- **Full docs:** `db/migrations/README_notification_pipeline.md`
- **This file:** `db/migrations/N8N_WORKFLOW_QUICKREF.md`
