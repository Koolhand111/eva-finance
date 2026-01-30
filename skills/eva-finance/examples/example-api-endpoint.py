"""
EVA-Finance API Endpoint Examples

Real examples extracted from eva-api/app.py showing standard patterns
for FastAPI endpoints with database operations.

Source: eva-api/app.py
"""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from psycopg2.extras import Json, RealDictCursor

from eva_common.db import get_connection

app = FastAPI(title="EVA-Finance API")


# ------------------------------------
# Pydantic Models
# ------------------------------------
class IntakeMessage(BaseModel):
    source: str
    platform_id: Optional[str] = None
    timestamp: str
    text: str
    url: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# ------------------------------------
# Health Check Endpoint
# ------------------------------------
@app.get("/health")
def health():
    """
    Simple health check endpoint.

    Used by:
    - Docker healthcheck
    - Load balancer probes
    - Monitoring systems

    Returns:
        {"status": "ok"}
    """
    return {"status": "ok"}


# ------------------------------------
# POST Endpoint with Insert
# ------------------------------------
@app.post("/intake/message")
def intake_message(msg: IntakeMessage):
    """
    Ingest a raw message for processing.

    Key patterns:
    1. Use get_connection() context manager
    2. Nested cursor context manager
    3. RETURNING clause to get inserted ID
    4. ON CONFLICT for idempotency
    5. Manual commit (autocommit is off)
    6. HTTPException for error responses

    Args:
        msg: IntakeMessage payload

    Returns:
        {"status": "ok", "id": <new_id>} on success
        {"status": "received", "duplicate": True} if already exists
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO raw_messages (source, platform_id, timestamp, text, url, meta)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source, platform_id) DO NOTHING
                    RETURNING id;
                    """,
                    (
                        msg.source,
                        msg.platform_id,
                        msg.timestamp,
                        msg.text,
                        msg.url,
                        Json(msg.meta)  # Convert dict to JSONB
                    )
                )
                result = cur.fetchone()
                conn.commit()

                # Handle duplicate detection
                if result is None:
                    return {"status": "received", "duplicate": True}

                return {"status": "ok", "id": result[0]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------
# GET Endpoint with Query Parameters
# ------------------------------------
@app.get("/events")
def list_events(
    ack: Optional[bool] = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
):
    """
    List signal events with filtering.

    Key patterns:
    1. Query parameters with validation (ge=1, le=500)
    2. Optional boolean filter
    3. Manual result serialization (no ORM)
    4. Date/datetime handling (.isoformat())

    Args:
        ack: Filter by acknowledged status
        limit: Max results (1-500)

    Returns:
        {"count": n, "events": [...]}
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, event_type, tag, brand, day, severity, payload, created_at, acknowledged
                    FROM signal_events
                    WHERE acknowledged = %s
                    ORDER BY id DESC
                    LIMIT %s;
                    """,
                    (ack, limit),
                )
                rows = cur.fetchall()

        # Manual serialization (tuple to dict)
        events = []
        for r in rows:
            events.append(
                {
                    "id": r[0],
                    "event_type": r[1],
                    "tag": r[2],
                    "brand": r[3],
                    "day": str(r[4]),  # date to string
                    "severity": r[5],
                    "payload": r[6],   # JSONB returned as dict
                    "created_at": r[7].isoformat(),
                    "acknowledged": r[8],
                }
            )

        return {"count": len(events), "events": events}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------
# POST Endpoint with Path Parameter
# ------------------------------------
@app.post("/events/{event_id}/ack")
def ack_event(event_id: int):
    """
    Acknowledge a signal event.

    Key patterns:
    1. Path parameter for resource ID
    2. UPDATE with RETURNING to verify existence
    3. 404 handling for not found
    4. Re-raise HTTPException to preserve status code

    Args:
        event_id: ID of event to acknowledge

    Returns:
        {"status": "ok", "id": <event_id>}

    Raises:
        HTTPException 404: If event not found
        HTTPException 500: On database error
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE signal_events
                    SET acknowledged = TRUE
                    WHERE id = %s
                    RETURNING id;
                    """,
                    (event_id,),
                )
                updated = cur.fetchone()
                conn.commit()

                if not updated:
                    raise HTTPException(status_code=404, detail="Event not found")

                return {"status": "ok", "id": updated[0]}

    except HTTPException:
        raise  # Re-raise to preserve 404 status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------
# Using RealDictCursor for Named Access
# ------------------------------------
@app.get("/events/{event_id}")
def get_event(event_id: int):
    """
    Get a single event with RealDictCursor.

    Key patterns:
    1. RealDictCursor for dict-style row access
    2. Direct dict conversion from row

    Args:
        event_id: Event ID

    Returns:
        Event as dictionary
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM signal_events WHERE id = %s",
                    (event_id,)
                )
                row = cur.fetchone()

                if not row:
                    raise HTTPException(status_code=404, detail="Event not found")

                # RealDictCursor returns dict-like rows
                result = dict(row)
                # Handle datetime serialization
                if result.get("created_at"):
                    result["created_at"] = result["created_at"].isoformat()
                if result.get("day"):
                    result["day"] = str(result["day"])

                return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
