from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from psycopg2.extras import Json

from eva_common.db import get_connection

app = FastAPI(title="EVA-Finance API")


# ------------------------------------
# Raw Message Intake Model
# ------------------------------------
class IntakeMessage(BaseModel):
    source: str
    platform_id: Optional[str] = None
    timestamp: str
    text: str
    url: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# ------------------------------------
# Health Check
# ------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------
# Save Raw Message
# ------------------------------------
@app.post("/intake/message")
def intake_message(msg: IntakeMessage):
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
                        Json(msg.meta)
                    )
                )
                result = cur.fetchone()
                conn.commit()

                if result is None:
                    return {"status": "received", "duplicate": True}

                return {"status": "ok", "id": result[0]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------
# Processed Message Model
# ------------------------------------
class ProcessedMessage(BaseModel):
    raw_id: int
    brand: list[str] = Field(default_factory=list)
    product: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    intent: Optional[str] = None
    tickers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ------------------------------------
# Save Processed Message
# ------------------------------------
@app.post("/processed")
def save_processed(msg: ProcessedMessage):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO processed_messages
                        (raw_id, brand, product, category, sentiment, intent, tickers, tags)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        msg.raw_id,
                        msg.brand,
                        msg.product,
                        msg.category,
                        msg.sentiment,
                        msg.intent,
                        msg.tickers,
                        msg.tags
                    )
                )
                new_id = cur.fetchone()[0]
                conn.commit()

        return {"status": "ok", "id": new_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/events")
def list_events(
    ack: Optional[bool] = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
):
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

        events = []
        for r in rows:
            events.append(
                {
                    "id": r[0],
                    "event_type": r[1],
                    "tag": r[2],
                    "brand": r[3],
                    "day": str(r[4]),
                    "severity": r[5],
                    "payload": r[6],
                    "created_at": r[7].isoformat(),
                    "acknowledged": r[8],
                }
            )

        return {"count": len(events), "events": events}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/events/{event_id}/ack")
def ack_event(event_id: int):
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
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
