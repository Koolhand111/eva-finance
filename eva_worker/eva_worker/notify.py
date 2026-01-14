"""
Notification polling for EVA-Finance recommendations.

Polls recommendation_drafts table for approved recommendations that haven't been
notified yet, sends them to ntfy, and tracks notification status.
"""
from __future__ import annotations

import os
import logging
import subprocess
from typing import Dict
import requests
from psycopg2.extras import RealDictCursor

from eva_common.db import get_connection
from eva_common.config import app_settings

logger = logging.getLogger(__name__)

# Configuration from eva_common
NTFY_URL = app_settings.ntfy_url

MAX_RETRY_ATTEMPTS = 3


def poll_and_notify() -> Dict[str, int]:
    """
    Poll recommendation_drafts for pending notifications and send to ntfy.

    Returns:
        Dict with 'sent' and 'failed' counts
    """
    print("[EVA-NOTIFY] poll_and_notify() called", flush=True)
    stats = {"sent": 0, "failed": 0}

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
                    print("[EVA-NOTIFY] No pending notifications", flush=True)
                    return stats

                print(f"[EVA-NOTIFY] Found {len(pending)} pending notifications", flush=True)
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

                        print(f"[EVA-NOTIFY] ✓ Sent notification for draft_id={draft_id} ({brand}/{tag})", flush=True)
                        logger.info(f"[EVA-NOTIFY] ✓ Sent notification for draft_id={draft_id} ({brand}/{tag})")
                        stats["sent"] += 1

                        # Trigger paper trade entry for approved signal
                        try:
                            logger.info(f"[PAPER-TRADE] Triggering paper trade entry for {brand}/{tag}")
                            script_path = os.path.join(os.environ.get('PROJECT_ROOT', '/app'), 'scripts/paper_trading/paper_trade_entry.py')
                            # Pass PYTHONPATH so subprocess can import eva_common
                            env = os.environ.copy()
                            env['PYTHONPATH'] = '/app'
                            result = subprocess.run(
                                ['python3', script_path],
                                capture_output=True,
                                text=True,
                                timeout=30,
                                env=env
                            )

                            if result.returncode == 0:
                                logger.info(f"[PAPER-TRADE] ✓ Paper trade entry successful: {result.stdout.strip()}")
                                print(f"[PAPER-TRADE] ✓ Created paper trade for {brand}/{tag}", flush=True)
                            else:
                                logger.warning(f"[PAPER-TRADE] ✗ Paper trade entry failed: {result.stderr.strip()}")
                                print(f"[PAPER-TRADE] ✗ Failed to create paper trade: {result.stderr.strip()}", flush=True)

                        except subprocess.TimeoutExpired:
                            logger.error("[PAPER-TRADE] Paper trade entry timed out after 30 seconds")
                            print("[PAPER-TRADE] ✗ Timeout after 30 seconds", flush=True)
                        except Exception as e:
                            logger.error(f"[PAPER-TRADE] Paper trade entry error: {e}")
                            print(f"[PAPER-TRADE] ✗ Error: {e}", flush=True)

                    except Exception as e:
                        # Record failure
                        error_msg = str(e)[:500]  # Truncate to avoid oversized errors
                        print(f"[EVA-NOTIFY] ✗ Failed to notify draft_id={draft_id}: {e}", flush=True)
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
        print(f"[EVA-NOTIFY] Poll/notify failed: {e}", flush=True)
        logger.error(f"[EVA-NOTIFY] Poll/notify failed: {e}")
        return stats


if __name__ == "__main__":
    # Standalone test mode
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    logger.info("Running notification poll test...")
    result = poll_and_notify()
    logger.info(f"Results: {result}")
