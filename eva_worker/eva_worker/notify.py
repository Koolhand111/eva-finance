"""
Notification polling for EVA-Finance recommendations.

Polls recommendation_drafts table for approved recommendations that haven't been
notified yet, sends them to ntfy, and tracks notification status.
"""
from __future__ import annotations

import os
import logging
from typing import Dict, Optional
import requests
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# Environment configuration
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
DB_NAME = os.getenv("POSTGRES_DB", "eva_finance")
DB_USER = os.getenv("POSTGRES_USER", "eva")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "eva_password_change_me")
NTFY_URL = os.getenv("NTFY_URL", "http://eva_ntfy:80")

MAX_RETRY_ATTEMPTS = 3


def _connect_pg():
    """Connect to PostgreSQL with RealDictCursor."""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    return conn, psycopg2.extras.RealDictCursor


def poll_and_notify() -> Dict[str, int]:
    """
    Poll recommendation_drafts for pending notifications and send to ntfy.

    Returns:
        Dict with 'sent' and 'failed' counts
    """
    conn, cursor_cls = _connect_pg()
    stats = {"sent": 0, "failed": 0}

    try:
        with conn:
            with conn.cursor(cursor_factory=cursor_cls) as cur:
                # Fetch pending notifications (atomic claim)
                cur.execute("""
                    SELECT
                        id,
                        signal_event_id,
                        brand,
                        tag,
                        final_confidence,
                        event_type,
                        notify_attempts
                    FROM recommendation_drafts
                    WHERE notify_ready = true
                      AND notified_at IS NULL
                      AND notify_attempts < %s
                    ORDER BY created_at ASC
                    LIMIT 10
                    FOR UPDATE SKIP LOCKED
                """, (MAX_RETRY_ATTEMPTS,))

                pending = cur.fetchall()

                if not pending:
                    return stats

                logger.info(f"[EVA-NOTIFY] Found {len(pending)} pending notifications")

                # Process each notification
                for rec in pending:
                    draft_id = rec["id"]
                    brand = rec["brand"] or "Unknown"
                    tag = rec["tag"] or "general"
                    confidence = float(rec["final_confidence"]) if rec["final_confidence"] else 0.0

                    try:
                        # Send to ntfy
                        ntfy_payload = {
                            "topic": "eva-recommendations",
                            "title": "EVA-Finance Recommendation",
                            "message": f"{brand} ({tag}) - Confidence: {confidence:.2f}",
                            "priority": 3,
                            "tags": ["chart_increasing", "moneybag"],
                            "extras": {
                                "draft_id": draft_id,
                                "signal_event_id": rec["signal_event_id"],
                                "brand": brand,
                                "tag": tag,
                                "confidence": confidence,
                            }
                        }

                        response = requests.post(
                            NTFY_URL,
                            json=ntfy_payload,
                            timeout=5
                        )
                        response.raise_for_status()

                        # Mark as notified (success)
                        cur.execute("""
                            UPDATE recommendation_drafts
                            SET
                                notified_at = NOW(),
                                notify_attempts = notify_attempts + 1,
                                last_notify_error = NULL
                            WHERE id = %s
                        """, (draft_id,))

                        logger.info(f"[EVA-NOTIFY] ✓ Sent notification for draft_id={draft_id} ({brand}/{tag})")
                        stats["sent"] += 1

                    except Exception as e:
                        # Record failure
                        error_msg = str(e)[:500]  # Truncate to avoid oversized errors
                        logger.error(f"[EVA-NOTIFY] ✗ Failed to notify draft_id={draft_id}: {e}")

                        cur.execute("""
                            UPDATE recommendation_drafts
                            SET
                                notify_attempts = notify_attempts + 1,
                                last_notify_error = %s
                            WHERE id = %s
                        """, (error_msg, draft_id))

                        stats["failed"] += 1

                conn.commit()

        return stats

    except Exception as e:
        logger.error(f"[EVA-NOTIFY] Poll/notify failed: {e}")
        return stats
    finally:
        conn.close()


if __name__ == "__main__":
    # Standalone test mode
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logger.info("Running notification poll test...")
    result = poll_and_notify()
    logger.info(f"Results: {result}")
