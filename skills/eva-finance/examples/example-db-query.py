"""
EVA-Finance Database Query Examples

Real examples extracted from various EVA-Finance services showing standard
patterns for database operations.

Sources:
- eva_common/db.py (connection pooling)
- eva_worker/eva_worker/notify.py (RealDictCursor)
- eva_worker/eva_confidence_v1.py (complex queries)
- scripts/paper_trading/paper_trade_entry.py (transactions)
"""

import json
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from psycopg2.extras import RealDictCursor, Json


# ------------------------------------
# Connection Pool Pattern (from eva_common/db.py)
# ------------------------------------
"""
EVA-Finance uses a ThreadedConnectionPool for efficient connection reuse.

Key principles:
1. Connections are automatically returned to pool
2. Rollback on exception to reset connection state
3. Pool is created lazily on first use
4. Cleanup registered with atexit
"""

from eva_common.db import get_connection


# ------------------------------------
# Basic SELECT with Parameters
# ------------------------------------
def get_raw_message(message_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetch a single raw message by ID.

    Pattern: Basic SELECT with parameter substitution.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source, text, processed FROM raw_messages WHERE id = %s",
                (message_id,)  # Always use tuple for params
            )
            row = cur.fetchone()

            if row is None:
                return None

            # Manual tuple to dict conversion
            return {
                "id": row[0],
                "source": row[1],
                "text": row[2],
                "processed": row[3]
            }


# ------------------------------------
# RealDictCursor for Named Column Access
# ------------------------------------
def get_pending_signals() -> List[Dict[str, Any]]:
    """
    Fetch signals needing paper trades.

    Pattern: RealDictCursor for cleaner row access.
    Source: scripts/paper_trading/paper_trade_entry.py
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    se.id AS signal_event_id,
                    se.brand,
                    se.tag,
                    se.day AS signal_date,
                    se.payload->>'final_confidence' AS confidence
                FROM signal_events se
                LEFT JOIN paper_trades pt ON pt.signal_event_id = se.id
                WHERE se.event_type = 'RECOMMENDATION_ELIGIBLE'
                AND pt.id IS NULL
                ORDER BY se.day DESC
            """)

            # RealDictCursor returns list of dict-like rows
            results = cur.fetchall()
            return [dict(row) for row in results]


# ------------------------------------
# INSERT with RETURNING
# ------------------------------------
def create_signal_event(
    event_type: str,
    tag: str,
    brand: str,
    payload: Dict[str, Any]
) -> int:
    """
    Create a signal event and return its ID.

    Pattern: INSERT ... RETURNING for getting generated ID.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO signal_events (event_type, tag, brand, day, severity, payload)
                VALUES (%s, %s, %s, CURRENT_DATE, 'warning', %s::jsonb)
                RETURNING id;
                """,
                (event_type, tag, brand, json.dumps(payload))
            )
            new_id = cur.fetchone()[0]
            conn.commit()  # Manual commit required
            return new_id


# ------------------------------------
# Idempotent Insert with ON CONFLICT
# ------------------------------------
def upsert_confidence_score(
    day,
    tag: str,
    brand: str,
    scores: Dict[str, float]
) -> None:
    """
    Insert or update confidence scores.

    Pattern: ON CONFLICT ... DO UPDATE for idempotent operations.
    Source: eva_worker/eva_confidence_v1.py
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO eva_confidence_v1 (
                    day, tag, brand,
                    acceleration_score, intent_score, spread_score,
                    final_confidence, band, scoring_version, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'v1', %s::jsonb)
                ON CONFLICT (day, tag, brand, scoring_version)
                DO UPDATE SET
                    acceleration_score = EXCLUDED.acceleration_score,
                    intent_score = EXCLUDED.intent_score,
                    spread_score = EXCLUDED.spread_score,
                    final_confidence = EXCLUDED.final_confidence,
                    band = EXCLUDED.band,
                    details = EXCLUDED.details,
                    computed_at = NOW();
            """, (
                day, tag, brand,
                scores["acceleration"],
                scores["intent"],
                scores["spread"],
                scores["final"],
                scores["band"],
                json.dumps(scores)
            ))
            conn.commit()


# ------------------------------------
# Atomic Claim with FOR UPDATE SKIP LOCKED
# ------------------------------------
def claim_pending_notifications(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Atomically claim pending notifications for processing.

    Pattern: FOR UPDATE SKIP LOCKED prevents race conditions.
    Source: eva_worker/eva_worker/notify.py

    This pattern is crucial for multi-worker scenarios where
    multiple workers might try to process the same records.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            """, (limit,))

            return [dict(row) for row in cur.fetchall()]


# ------------------------------------
# Batch Insert with executemany
# ------------------------------------
def insert_raw_posts(posts: List[Dict[str, Any]]) -> int:
    """
    Insert multiple posts efficiently.

    Pattern: executemany for batch operations.
    Note: Still use ON CONFLICT for idempotency.
    """
    if not posts:
        return 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Prepare data as list of tuples
            data = [
                (
                    post["source"],
                    post["platform_id"],
                    post["timestamp"],
                    post["text"],
                    post.get("url"),
                    Json(post.get("meta", {}))
                )
                for post in posts
            ]

            # Use INSERT ... ON CONFLICT for each
            cur.executemany(
                """
                INSERT INTO raw_messages (source, platform_id, timestamp, text, url, meta)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, platform_id) DO NOTHING
                """,
                data
            )

            inserted = cur.rowcount
            conn.commit()
            return inserted


# ------------------------------------
# Transaction with Multiple Statements
# ------------------------------------
def process_and_mark_complete(raw_id: int, extracted_data: Dict[str, Any]) -> bool:
    """
    Insert processed data and mark raw as complete in one transaction.

    Pattern: Multiple statements in single transaction for atomicity.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Statement 1: Insert processed message
                cur.execute(
                    """
                    INSERT INTO processed_messages
                      (raw_id, brand, product, category, sentiment, intent, tickers, tags)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        raw_id,
                        extracted_data["brand"],
                        extracted_data["product"],
                        extracted_data["category"],
                        extracted_data["sentiment"],
                        extracted_data["intent"],
                        extracted_data["tickers"],
                        extracted_data["tags"],
                    )
                )
                processed_id = cur.fetchone()[0]

                # Statement 2: Mark raw as processed
                cur.execute(
                    "UPDATE raw_messages SET processed = TRUE WHERE id = %s",
                    (raw_id,)
                )

                # Single commit for both operations
                conn.commit()
                return True

    except Exception as e:
        # Connection automatically rolls back on exception
        print(f"Transaction failed: {e}")
        return False


# ------------------------------------
# Using JSONB Operators
# ------------------------------------
def get_signals_by_confidence(min_confidence: float) -> List[Dict[str, Any]]:
    """
    Query signals using JSONB field extraction.

    Pattern: JSONB operators for flexible querying.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    id,
                    event_type,
                    tag,
                    brand,
                    day,
                    payload->>'final_confidence' AS confidence
                FROM signal_events
                WHERE (payload->>'final_confidence')::numeric >= %s
                ORDER BY (payload->>'final_confidence')::numeric DESC
                LIMIT 50
            """, (min_confidence,))

            return [dict(row) for row in cur.fetchall()]


# ------------------------------------
# Array Containment Queries
# ------------------------------------
def find_messages_with_brand(brand: str) -> List[Dict[str, Any]]:
    """
    Find processed messages containing a specific brand.

    Pattern: Array containment with GIN index.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Use @> operator for array containment
            cur.execute("""
                SELECT id, raw_id, brand, tags, sentiment
                FROM processed_messages
                WHERE brand @> ARRAY[%s]::text[]
                ORDER BY created_at DESC
                LIMIT 100
            """, (brand,))

            return [dict(row) for row in cur.fetchall()]


# ------------------------------------
# Usage Example
# ------------------------------------
if __name__ == "__main__":
    # Example: Get pending signals
    signals = get_pending_signals()
    print(f"Found {len(signals)} pending signals")

    # Example: Idempotent upsert
    upsert_confidence_score(
        day="2026-01-17",
        tag="running",
        brand="Nike",
        scores={
            "acceleration": 0.75,
            "intent": 0.82,
            "spread": 0.65,
            "final": 0.74,
            "band": "WATCHLIST"
        }
    )
    print("Upserted confidence score")
