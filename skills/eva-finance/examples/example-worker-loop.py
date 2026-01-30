"""
EVA-Finance Worker Loop Examples

Real examples extracted from eva_worker/worker.py and eva_worker/eva_worker/notify.py
showing the standard patterns for background workers.

Sources:
- eva_worker/worker.py (main worker loop)
- eva_worker/eva_worker/notify.py (notification polling)
"""

import time
import json
import logging
from typing import Dict, Any

from eva_common.db import get_connection
from eva_common.config import app_settings

# Configure logging with EVA-standard format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ------------------------------------
# Main Worker Loop Pattern
# ------------------------------------
def process_batch(limit: int = 20) -> int:
    """
    Process a batch of unprocessed messages.

    Pattern highlights:
    1. Query for unprocessed rows (processed = FALSE)
    2. Process each row individually
    3. Mark as processed on success
    4. Return count of processed items

    Args:
        limit: Max rows to process in one batch

    Returns:
        Number of successfully processed rows
    """
    # 1) Fetch unprocessed rows
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text
                FROM raw_messages
                WHERE processed = FALSE
                ORDER BY id ASC
                LIMIT %s;
                """,
                (limit,),
            )
            rows = cur.fetchall()

    if not rows:
        return 0

    # 2) Process each row
    count = 0
    for raw_id, text in rows:
        try:
            # Extract data from text (LLM or fallback)
            data = extract_data(raw_id, text)

            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Insert processed row
                    cur.execute(
                        """
                        INSERT INTO processed_messages
                          (raw_id, brand, product, category, sentiment, intent, tickers, tags)
                        VALUES
                          (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            data["raw_id"],
                            data["brand"],
                            data["product"],
                            data["category"],
                            data["sentiment"],
                            data["intent"],
                            data["tickers"],
                            data["tags"],
                        ),
                    )

                    # Mark raw as processed
                    cur.execute(
                        "UPDATE raw_messages SET processed = TRUE WHERE id = %s;",
                        (raw_id,),
                    )

                    conn.commit()

            count += 1

        except Exception as e:
            logger.error(f"[EVA-WORKER] Failed processing raw_id={raw_id}: {e}")

    return count


def extract_data(raw_id: int, text: str) -> Dict[str, Any]:
    """Placeholder for LLM extraction logic."""
    return {
        "raw_id": raw_id,
        "brand": [],
        "product": [],
        "category": [],
        "sentiment": "neutral",
        "intent": "none",
        "tickers": [],
        "tags": [],
    }


def emit_trigger_events():
    """
    Emit signal events based on database views.

    Pattern highlights:
    1. Query trigger views (precomputed in SQL)
    2. Insert events with ON CONFLICT DO NOTHING (idempotent)
    3. Use JSONB for flexible payloads
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Query the trigger view
            cur.execute("""
                SELECT tag, day, confidence
                FROM v_trigger_tag_elevated
                ORDER BY day DESC;
            """)
            elevated = cur.fetchall()

            for tag, day, confidence in elevated:
                # Idempotent insert with ON CONFLICT
                cur.execute("""
                    INSERT INTO signal_events (event_type, tag, day, severity, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT DO NOTHING;
                """, (
                    "TAG_ELEVATED",
                    tag,
                    day,
                    "warning",
                    json.dumps({"confidence": float(confidence)})
                ))

            conn.commit()


# ------------------------------------
# Polling with Interval Pattern
# ------------------------------------
def poll_and_notify() -> Dict[str, int]:
    """
    Poll for pending notifications and send them.

    Pattern highlights:
    1. SELECT ... FOR UPDATE SKIP LOCKED (atomic claim)
    2. Process in batch with individual error handling
    3. Track stats (sent/failed counts)
    4. Single commit at end

    Source: eva_worker/eva_worker/notify.py

    Returns:
        Dict with 'sent' and 'failed' counts
    """
    from psycopg2.extras import RealDictCursor

    logger.info("[EVA-NOTIFY] poll_and_notify() called")
    stats = {"sent": 0, "failed": 0}

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Atomic claim with FOR UPDATE SKIP LOCKED
                cur.execute("""
                    SELECT
                        id,
                        signal_event_id,
                        brand,
                        tag,
                        final_confidence
                    FROM recommendation_drafts
                    WHERE notify_ready = true
                      AND notified_at IS NULL
                      AND notify_attempts < 3
                    ORDER BY created_at ASC
                    LIMIT 10
                    FOR UPDATE SKIP LOCKED
                """)

                pending = cur.fetchall()

                if not pending:
                    logger.debug("[EVA-NOTIFY] No pending notifications")
                    return stats

                logger.info(f"[EVA-NOTIFY] Found {len(pending)} pending notifications")

                # Process each notification
                for rec in pending:
                    draft_id = rec["id"]

                    try:
                        # Send notification (placeholder)
                        send_notification(rec)

                        # Mark as notified (success)
                        cur.execute("""
                            UPDATE recommendation_drafts
                            SET
                                notified_at = NOW(),
                                notify_attempts = notify_attempts + 1,
                                last_notify_error = NULL
                            WHERE id = %s
                        """, (draft_id,))

                        logger.info(f"[EVA-NOTIFY] ✓ Sent notification for draft_id={draft_id}")
                        stats["sent"] += 1

                    except Exception as e:
                        # Record failure
                        error_msg = str(e)[:500]
                        logger.error(f"[EVA-NOTIFY] ✗ Failed draft_id={draft_id}: {e}")

                        cur.execute("""
                            UPDATE recommendation_drafts
                            SET
                                notify_attempts = notify_attempts + 1,
                                last_notify_error = %s
                            WHERE id = %s
                        """, (error_msg, draft_id))

                        stats["failed"] += 1

                # Single commit for all updates
                conn.commit()

        return stats

    except Exception as e:
        logger.error(f"[EVA-NOTIFY] Poll/notify failed: {e}")
        return stats


def send_notification(record: Dict[str, Any]) -> None:
    """Placeholder for actual notification sending."""
    pass


# ------------------------------------
# Main Worker Entry Point
# ------------------------------------
def main():
    """
    Main worker loop.

    Pattern highlights:
    1. Continuous while True loop
    2. Multiple tasks with different intervals
    3. Time-based conditional execution
    4. Graceful sleep between iterations
    """
    logger.info("[EVA-WORKER] Starting up...")

    # Track last execution times for interval-based tasks
    last_notification_poll = 0
    NOTIFICATION_POLL_INTERVAL = app_settings.notification_poll_interval  # 60 seconds

    while True:
        # Task 1: Process batch (every iteration)
        n = process_batch(limit=20)
        if n:
            logger.info(f"[EVA-WORKER] Processed {n} messages")

        # Task 2: Emit trigger events (every iteration)
        emit_trigger_events()

        # Task 3: Notification polling (every NOTIFICATION_POLL_INTERVAL)
        current_time = time.time()
        if (current_time - last_notification_poll) >= NOTIFICATION_POLL_INTERVAL:
            try:
                stats = poll_and_notify()
                if stats["sent"] > 0 or stats["failed"] > 0:
                    logger.info(
                        f"[EVA-WORKER] Notifications: {stats['sent']} sent, "
                        f"{stats['failed']} failed"
                    )
            except Exception as e:
                logger.error(f"[EVA-WORKER] Notification polling error: {e}")
            finally:
                last_notification_poll = current_time

        # Sleep between iterations
        time.sleep(10)


if __name__ == "__main__":
    main()
