"""Notification polling for EVA-Finance recommendations."""
import logging
import os
from typing import Dict, List
import requests
from psycopg2.extras import RealDictCursor
import psycopg2

logger = logging.getLogger(__name__)

class NotificationError(Exception):
    pass

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "eva_db"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "eva_finance"),
        user=os.getenv("DB_USER", "eva"),
        password=os.getenv("DB_PASSWORD", "eva_password_change_me"),
        cursor_factory=RealDictCursor
    )

def poll_and_notify(limit=10, max_attempts=3):
    """Main entry point - polls and sends notifications."""
    conn = get_db_connection()
    stats = {'sent': 0, 'failed': 0}
    
    try:
        # Fetch pending
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT rd.draft_id, rd.signal_event_id, rd.brand, rd.tag, 
                       rd.final_confidence
                FROM recommendation_drafts rd
                WHERE rd.notify_ready = true
                  AND rd.notified_at IS NULL
                  AND rd.notify_attempts < %s
                ORDER BY rd.created_at ASC
                LIMIT %s
            """, (max_attempts, limit))
            pending = cursor.fetchall()
        
        if not pending:
            return stats
        
        logger.info(f"Found {len(pending)} pending notifications")
        
        # Process each
        for rec in pending:
            draft_id = rec['draft_id']
            try:
                # Send to ntfy
                response = requests.post(
                    os.getenv("NTFY_URL", "http://eva_ntfy:80"),
                    json={
                        "topic": "eva-recommendations",
                        "message": f"{rec['brand']} ({rec['tag']}) - Confidence: {rec['final_confidence']:.2f}",
                        "title": "EVA-Finance Recommendation",
                        "priority": 3,
                        "tags": ["chart_increasing", "moneybag"],
                        "extras": {
                            "draft_id": draft_id,
                            "brand": rec['brand'],
                            "tag": rec['tag']
                        }
                    },
                    timeout=5
                )
                response.raise_for_status()
                
                # Mark sent
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE recommendation_drafts
                        SET notified_at = NOW(), 
                            notify_attempts = notify_attempts + 1,
                            last_notify_error = NULL
                        WHERE draft_id = %s
                    """, (draft_id,))
                conn.commit()
                
                logger.info(f"✓ Sent notification for draft_id={draft_id} ({rec['brand']}/{rec['tag']})")
                stats['sent'] += 1
                
            except Exception as e:
                logger.error(f"✗ Failed draft_id={draft_id}: {e}")
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE recommendation_drafts
                        SET notify_attempts = notify_attempts + 1,
                            last_notify_error = %s
                        WHERE draft_id = %s
                    """, (str(e)[:500], draft_id))
                conn.commit()
                stats['failed'] += 1
        
        return stats
    finally:
        conn.close()
