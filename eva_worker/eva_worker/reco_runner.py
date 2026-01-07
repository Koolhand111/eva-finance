# eva_worker/reco_runner.py
"""
EVA-Finance Recommendation Draft Runner

Purpose:
- Poll for RECOMMENDATION_ELIGIBLE events that do not yet have a draft row.
- Generate the evidence bundle + markdown draft via eva_worker.eva_worker.generate.generate_from_db
- Record the draft in recommendation_drafts (idempotent; ON CONFLICT DO NOTHING)

Non-goals:
- No scoring
- No ingestion
- No notifications
- No LLM usage
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

# Your existing generator (already writes bundle + markdown)
# NOTE: adjust import if your package layout differs.
from .generate import generate_from_db


def _build_database_url() -> str:
    """
    Build database connection URL.
    Prefers DATABASE_URL if set, otherwise builds from POSTGRES_* variables.
    """
    # Option 1: Use DATABASE_URL if present
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Option 2: Build from individual POSTGRES_* variables
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USER")
    pw = os.getenv("POSTGRES_PASSWORD")

    missing = [k for k, v in {
        "POSTGRES_HOST": host,
        "POSTGRES_DB": db,
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": pw,
    }.items() if not v]

    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    return f"postgres://{user}:{pw}@{host}:{port}/{db}"


PENDING_EVENT_SQL = """
SELECT se.id
FROM public.signal_events se
LEFT JOIN public.recommendation_drafts rd
  ON rd.signal_event_id = se.id
WHERE se.event_type = 'RECOMMENDATION_ELIGIBLE'
  AND rd.signal_event_id IS NULL
ORDER BY se.created_at ASC
LIMIT 1;
"""

INSERT_DRAFT_SQL = """
INSERT INTO public.recommendation_drafts (
  signal_event_id,
  event_type,
  brand,
  tag,
  event_time,

  confidence_snapshot_id,
  confidence_computed_at,
  final_confidence,
  band,

  bundle_path,
  bundle_sha256,
  markdown_path
)
VALUES (
  %(signal_event_id)s,
  %(event_type)s,
  %(brand)s,
  %(tag)s,
  %(event_time)s,

  %(confidence_snapshot_id)s,
  %(confidence_computed_at)s,
  %(final_confidence)s,
  %(band)s,

  %(bundle_path)s,
  %(bundle_sha256)s,
  %(markdown_path)s
)
ON CONFLICT (signal_event_id) DO NOTHING;
"""


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def get_conn():
    """
    Connects to Postgres using either:
      1) DATABASE_URL if present
      2) Otherwise builds DSN from POSTGRES_* env vars
    """
    dsn = _build_database_url()
    return psycopg2.connect(dsn, cursor_factory=RealDictCursor)


def fetch_next_pending_event_id(conn) -> Optional[int]:
    with conn.cursor() as cur:
        cur.execute(PENDING_EVENT_SQL)
        row = cur.fetchone()
        return int(row["id"]) if row else None


def _normalize_generator_result(event_id: int, result: Any) -> Dict[str, Any]:
    """
    generate_from_db() may currently:
      - return a dict (ideal)
      - return None (prints paths only)
    We normalize to the dict INSERT_DRAFT_SQL expects.

    If your generate_from_db already returns a dict with these keys,
    this becomes a passthrough.
    """
    if isinstance(result, dict):
        # Ensure required keys exist; raise early if not.
        required = [
            "signal_event_id",
            "event_type",
            "brand",
            "tag",
            "event_time",
            "confidence_snapshot_id",
            "confidence_computed_at",
            "final_confidence",
            "band",
            "bundle_path",
            "bundle_sha256",
            "markdown_path",
        ]
        missing = [k for k in required if k not in result]
        if missing:
            raise RuntimeError(
                "generate_from_db returned a dict but is missing keys: "
                + ", ".join(missing)
            )
        return result

    # If generate_from_db doesn't return anything yet, you have two choices:
    # 1) Update generate_from_db to return a dict (recommended)
    # 2) Parse printed output (not recommended)
    raise RuntimeError(
        f"generate_from_db(event_id={event_id}) did not return a dict. "
        "Please update generate_from_db to return a structured result dict "
        "with bundle/markdown paths and snapshot fields."
    )


def insert_draft_row(conn, draft: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(INSERT_DRAFT_SQL, draft)


def main() -> int:
    """
    One-shot runner:
    - If an eligible event exists, generate + record one draft.
    - Otherwise exit 0.
    """
    try:
        conn = get_conn()
    except Exception as e:
        print(f"[reco_runner] DB connection failed: {e}", file=sys.stderr)
        return 2

    conn.autocommit = False

    try:
        event_id = fetch_next_pending_event_id(conn)
        if not event_id:
            print("[reco_runner] No pending RECOMMENDATION_ELIGIBLE events.")
            conn.rollback()
            return 0

        print(f"[reco_runner] Found pending eligible event_id={event_id}")

        # Call your existing generator.
        # NOTE: adjust args to match your signature (seen in generate.py).
        gen_result = generate_from_db(event_id=event_id)

        draft = _normalize_generator_result(event_id, gen_result)

        insert_draft_row(conn, draft)
        conn.commit()

        print(
            "[reco_runner] Draft recorded: "
            f"event_id={draft['signal_event_id']} "
            f"md={draft['markdown_path']} "
            f"bundle={draft['bundle_path']} "
            f"sha={draft['bundle_sha256']}"
        )
        return 0

    except Exception as e:
        conn.rollback()
        print(f"[reco_runner] ERROR: {e}", file=sys.stderr)
        return 1

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
