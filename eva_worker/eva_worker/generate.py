from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal
from .hashutil import sha256_hex
from .render import render_markdown
from .sanitize import sanitize_text

GENERATOR_VERSION = os.getenv("EVA_WORKER_VERSION", "dev")
OUTPUT_ROOT = Path(os.getenv("EVA_RECO_OUTPUT_DIR", "eva_worker/output/recommendations"))

# Postgres connection env vars
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "eva")
PG_USER = os.getenv("POSTGRES_USER", "eva")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

DEFAULT_EVIDENCE_DAYS = int(os.getenv("EVA_RECO_DEFAULT_EVIDENCE_DAYS", "7"))
DEFAULT_EVIDENCE_LIMIT = int(os.getenv("EVA_RECO_EVIDENCE_LIMIT", "50"))


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    out: List[str] = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in [" ", "-", "_", "."]:
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "unknown-entity"


def _read_queries_sql() -> str:
    here = Path(__file__).resolve().parent
    return (here / "queries.sql").read_text(encoding="utf-8")


def _split_sql_statements(sql_text: str) -> List[str]:
    """
    Minimal splitter: expects each query ends with ';' and no semicolons inside strings.
    Works fine for our controlled queries.sql.
    """
    chunks: List[str] = []
    buf: List[str] = []
    for line in sql_text.splitlines():
        buf.append(line)
        if ";" in line:
            joined = "\n".join(buf).strip()
            if joined:
                chunks.append(joined)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        chunks.append(tail)
    return chunks


def _json_default(o: Any):
    # psycopg2 returns numeric as Decimal; JSON can't serialize it by default
    if isinstance(o, Decimal):
        # Keep precision but make it JSON-friendly
        return float(o)
    if isinstance(o, datetime):
        return o.astimezone(timezone.utc).isoformat()
    return str(o)


def _write_gz_json(path: Path, payload: Dict[str, Any]) -> str:
    """
    Writes a gzipped JSON file. Returns SHA256 of the *uncompressed* JSON bytes.
    """
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        default=_json_default,
    ).encode("utf-8")
    digest = sha256_hex(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(raw)
    return digest


def _ensure_append_only(path: Path, force: bool = False) -> None:
    """
    Evidence bundles should be append-only. If a bundle already exists, refuse to overwrite.
    This prevents accidental history rewrites.
    """
    if path.exists() and not force:
        raise RuntimeError(f"Refusing to overwrite existing file: {path}")



def _connect_pg():
    """
    Lazy import psycopg2 so demo mode can run even if dependency isn't installed.
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    return conn, psycopg2.extras.RealDictCursor


def _run_query(cur, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    cur.execute(sql, params)
    return list(cur.fetchall())


def _parse_ts(val: Any) -> Optional[datetime]:
    """
    Parse timestamptz-ish values coming from JSON payloads.
    Accepts:
      - datetime (pass-through)
      - ISO strings (including Z)
      - None
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        # tolerate trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt
        except Exception:
            return None
    return None


def _derive_window(event_time: datetime, payload: Dict[str, Any]) -> Tuple[datetime, datetime]:
    """
    Derive evidence window:
      1) payload.window_start/window_end if present and parseable
      2) fallback: [event_time - DEFAULT_EVIDENCE_DAYS, event_time]
    """
    p = payload or {}
    ws = _parse_ts(p.get("window_start") or p.get("evidence_window_start"))
    we = _parse_ts(p.get("window_end") or p.get("evidence_window_end"))

    if we is None:
        we = event_time
    if ws is None:
        ws = we - timedelta(days=DEFAULT_EVIDENCE_DAYS)
    return ws, we


def _load_from_db(
    event_id: int,
    evidence_limit: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Loads:
      - anchor event (by id)
      - confidence snapshot as-of event time (optional until schema aligned)
      - evidence items (optional until schema aligned)
    Returns: (anchor, snapshot, evidence_rows)
    """
    sql_text = _read_queries_sql()
    statements = _split_sql_statements(sql_text)

    if len(statements) < 3:
        raise RuntimeError("queries.sql must contain at least 3 SQL statements (anchor, snapshot, evidence).")

    anchor_sql = statements[0]
    snapshot_sql = statements[1]
    evidence_sql = statements[2]

    conn, cursor_cls = _connect_pg()

    try:
        with conn:
            with conn.cursor(cursor_factory=cursor_cls) as cur:
                # 1) Anchor
                anchor_rows = _run_query(cur, anchor_sql, {"event_id": event_id})
                if not anchor_rows:
                    raise RuntimeError(f"No signal_event found for id={event_id}")
                anchor = anchor_rows[0]

                # Ensure we have event_time as datetime
                event_time = anchor.get("event_time")
                if not isinstance(event_time, datetime):
                    raise RuntimeError("Anchor query must return event_time as a timestamp (timestamptz).")

                # Brand-first entity key (current schema)
                brand = (anchor.get("brand") or "").strip()
                tag = (anchor.get("tag") or "").strip()

                if not brand:
                    raise RuntimeError("Anchor event must include brand (entity key).")

                entity_key = brand  # canonical entity identifier for v1 (string)
                anchor["entity_key"] = entity_key
                anchor["entity_name"] = brand  # renderer compatibility
                anchor["ticker"] = ""          # renderer compatibility
                anchor["tag"] = tag

                # Evidence window: from payload or default
                payload = anchor.get("payload") or {}
                window_start, window_end = _derive_window(event_time, payload)
                anchor["window_start"] = window_start
                anchor["window_end"] = window_end

                # 2) Snapshot (optional until schema is aligned)
                snapshot: Optional[Dict[str, Any]] = None
                snapshot_error: Optional[str] = None
                try:
                    snapshot_rows = _run_query(
                        cur,
                        snapshot_sql,
                        {
                            "entity_key": entity_key,
                            "tag": anchor.get("tag") or "",
                            "event_time": event_time,
                        },
                    )
                    snapshot = snapshot_rows[0] if snapshot_rows else None
                except Exception as e:
                    snapshot_error = f"{type(e).__name__}: {e}"

                # 3) Evidence (optional until schema is aligned)
                evidence_rows: List[Dict[str, Any]] = []
                evidence_error: Optional[str] = None
                try:
                    evidence_rows = _run_query(
                        cur,
                        evidence_sql,
                        {
                            "entity_key": entity_key,
                            "window_start": window_start,
                            "window_end": window_end,
                            "limit": evidence_limit,
                        },
                    )
                except Exception as e:
                    evidence_error = f"{type(e).__name__}: {e}"
                    evidence_rows = []

                if snapshot_error or evidence_error:
                    anchor["_query_warnings"] = {
                        "snapshot_error": snapshot_error,
                        "evidence_error": evidence_error,
                    }

                return anchor, snapshot, evidence_rows

    finally:
        conn.close()


def _build_evidence_items(evidence_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts DB rows into stable evidence bundle items.
    Raw text is canonical; sanitized is for display.
    """
    items: List[Dict[str, Any]] = []
    for r in evidence_rows:
        raw_text = r.get("raw_text") or ""
        created_at = r.get("created_at")
        items.append(
            {
                "processed_message_id": r.get("processed_message_id"),
                "raw_message_id": r.get("raw_message_id"),
                "created_at": (
                    created_at.astimezone(timezone.utc).isoformat()
                    if isinstance(created_at, datetime)
                    else None
                ),
                "source": {
                    "platform": r.get("source_platform"),
                    "subreddit": r.get("source_subreddit"),
                    "permalink": r.get("permalink"),
                },
                "raw": {"text": raw_text},
                "sanitized": {
                    "text": sanitize_text(raw_text, sanitize_urls=True, sanitize_usernames=True)
                },
                "processed": {
                    "sentiment": r.get("sentiment"),
                    "intent": r.get("intent"),
                    "tags": r.get("tags"),
                    "brand": r.get("brand"),
                    "weight": r.get("weight"),
                },
            }
        )
    return items


def generate_from_db(event_id: int, evidence_limit: int = DEFAULT_EVIDENCE_LIMIT, force: bool = False) -> Dict[str, Any]:

    """
    Main entrypoint (DB mode). Generates:
      - evidence bundle (.json.gz) [append-only]
      - recommendation markdown (.md)
    """
    anchor, snapshot, evidence_rows = _load_from_db(event_id, evidence_limit)

    entity_name = (anchor.get("entity_name") or "").strip() or "UNKNOWN"
    ticker = (anchor.get("ticker") or "").strip()
    entity_key = anchor.get("entity_key")  # brand string

    event_time: datetime = anchor["event_time"]
    window_start: datetime = anchor["window_start"]
    window_end: datetime = anchor["window_end"]

    entity_slug = slugify(entity_name or ticker or (entity_key or "unknown"))
    out_dir = OUTPUT_ROOT / entity_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build evidence items
    evidence_items = _build_evidence_items(evidence_rows)

    # Evidence bundle (canonical record)
    bundle: Dict[str, Any] = {
        "schema": "eva-finance-evidence-bundle",
        "schema_version": "v1.0",
        "anchor": {
            "signal_event_id": anchor.get("signal_event_id"),
            "event_type": anchor.get("event_type"),
            "event_time": event_time.astimezone(timezone.utc).isoformat(),
            "brand": anchor.get("brand"),
            "tag": anchor.get("tag"),
            "severity": anchor.get("severity"),
            "day": str(anchor.get("day")) if anchor.get("day") is not None else None,
            "entity": {"entity_key": entity_key, "name": entity_name, "ticker": ticker or None},
            "payload": anchor.get("payload") or {},
            "warnings": anchor.get("_query_warnings"),
        },
        "source_window": {
            "start": window_start.astimezone(timezone.utc).isoformat(),
            "end": window_end.astimezone(timezone.utc).isoformat(),
        },
        "confidence_snapshot": snapshot,
        "evidence_items": evidence_items,
        "generator": {"component": "eva_worker", "version": GENERATOR_VERSION},
    }

    bundle_path = out_dir / f"{anchor.get('signal_event_id')}_evidence.json.gz"
    if not force:
        _ensure_append_only(bundle_path, force=force)
    bundle_sha = _write_gz_json(bundle_path, bundle)


    # Message IDs used for traceability
    message_ids_used: List[int] = []
    for it in evidence_items:
        mid = it.get("processed_message_id") or it.get("raw_message_id")
        if mid is not None:
            try:
                message_ids_used.append(int(mid))
            except Exception:
                pass

    # Render Markdown
    md = render_markdown(
        schema_version="v1.0",
        generated_at_iso=datetime.now(timezone.utc).isoformat(),
        anchor={
            "signal_event_id": anchor.get("signal_event_id"),
            "event_type": anchor.get("event_type"),
            "event_time": event_time.isoformat(),
        },
        entity={
            "entity_key": entity_key,
            "name": entity_name,
            "ticker": ticker,
            "slug": entity_slug,
        },
        source_window={
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        evidence_meta={
            "bundle_path": str(bundle_path),
            "bundle_sha256": bundle_sha,
            "max_excerpts": 15,
            "max_chars_each": 400,
        },
        reproducibility={
            "component": "eva_worker",
            "version": GENERATOR_VERSION,
            "confidence_snapshot_id": (snapshot or {}).get("id") if isinstance(snapshot, dict) else None,
            "message_ids_used": message_ids_used,
        },
        llm_meta={
            "used": False,
            "provider": None,
            "model": None,
            "prompt_sha256": None,
            "response_sha256": None,
        },
        snapshot=snapshot,
        evidence_items=evidence_items,
        excerpt_max=15,
        excerpt_chars=400,
    )

    md_path = out_dir / f"{anchor.get('signal_event_id')}_EVA-Finance_Recommendation.md"
    if not force:
        _ensure_append_only(md_path, force=force)
    md_path.write_text(md, encoding="utf-8")

    return {
        "signal_event_id": anchor.get("signal_event_id"),
        "event_type": anchor.get("event_type"),
        "brand": anchor.get("brand"),
        "tag": anchor.get("tag"),
        "event_time": event_time.astimezone(timezone.utc).isoformat(),
        "confidence_snapshot_id": snapshot.get("id") if snapshot else None,
        "confidence_computed_at": snapshot.get("computed_at") if snapshot else None,
        "final_confidence": snapshot.get("final_confidence") if snapshot else None,
        "band": snapshot.get("band") if snapshot else None,

        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_sha,
        "markdown_path": str(md_path),
    }



def demo_generate(*, force: bool = False) -> Dict[str, Any]:
    """
    Demo mode (no DB): proves end-to-end artifact creation works.
    """
    now = datetime.now().astimezone()
    window_end = now
    window_start = now - timedelta(days=7)

    snapshot = {
        "id": 999,
        "final_confidence": 0.87,
        "band": "HIGH",
        "computed_at": now.astimezone(timezone.utc).isoformat(),
    }
    evidence_items = [
        {
            "processed_message_id": 101,
            "raw_message_id": 101,
            "created_at": now.astimezone(timezone.utc).isoformat(),
            "source": {"platform": "reddit", "subreddit": "MakeupAddiction", "permalink": "[link removed]"},
            "raw": {"text": "Everyone keeps recommending this brand lately — feels like it’s everywhere."},
            "sanitized": {"text": "Everyone keeps recommending this brand lately — feels like it’s everywhere."},
            "processed": {
                "sentiment": "positive",
                "intent": "evaluative",
                "tags": ["foundation"],
                "brand": ["DemoBrand"],
                "weight": 0.92,
            },
        }
    ]

    entity_slug = slugify("DemoBrand")
    out_dir = OUTPUT_ROOT / entity_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = {
        "schema": "eva-finance-evidence-bundle",
        "schema_version": "v1.0",
        "anchor": {
            "signal_event_id": 12345,
            "event_type": "RECOMMENDATION_ELIGIBLE",
            "event_time": now.astimezone(timezone.utc).isoformat(),
            "entity": {"entity_key": "DemoBrand", "name": "DemoBrand", "ticker": None},
        },
        "source_window": {
            "start": window_start.astimezone(timezone.utc).isoformat(),
            "end": window_end.astimezone(timezone.utc).isoformat(),
        },
        "confidence_snapshot": snapshot,
        "evidence_items": evidence_items,
        "generator": {"component": "eva_worker", "version": GENERATOR_VERSION},
    }

    bundle_path = out_dir / "12345_evidence.json.gz"
    md_path = out_dir / "12345_EVA-Finance_Recommendation.md"


    # Append-only protection (demo should behave like prod unless --force)
    if not force:
        _ensure_append_only(bundle_path, force=force)
        _ensure_append_only(md_path, force=force)

    bundle_sha = _write_gz_json(bundle_path, bundle)

    md = render_markdown(
        schema_version="v1.0",
        generated_at_iso=datetime.now(timezone.utc).isoformat(),
        anchor={"signal_event_id": 12345, "event_type": "RECOMMENDATION_ELIGIBLE", "event_time": now.isoformat()},
        entity={"entity_key": "DemoBrand", "name": "DemoBrand", "ticker": "", "slug": entity_slug},
        source_window={"start": window_start.isoformat(), "end": window_end.isoformat()},
        evidence_meta={"bundle_path": str(bundle_path), "bundle_sha256": bundle_sha, "max_excerpts": 15, "max_chars_each": 400},
        reproducibility={"component": "eva_worker", "version": GENERATOR_VERSION, "confidence_snapshot_id": snapshot.get("id"), "message_ids_used": [101]},
        llm_meta={"used": False, "provider": None, "model": None, "prompt_sha256": None, "response_sha256": None},
        snapshot=snapshot,
        evidence_items=evidence_items,
    )
    md_path.write_text(md, encoding="utf-8")

    return {
        "signal_event_id": 12345,
        "event_type": "RECOMMENDATION_ELIGIBLE",
        "brand": "DemoBrand",
        "tag": "demo",
        "event_time": now.astimezone(timezone.utc).isoformat(),
        "confidence_snapshot_id": snapshot.get("id"),
        "confidence_computed_at": snapshot.get("computed_at"),
        "final_confidence": snapshot.get("final_confidence"),
        "band": snapshot.get("band"),

        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_sha,
        "markdown_path": str(md_path),
    }



if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Generate EVA-Finance Recommendation artifacts.")
    p.add_argument("--event-id", type=int, help="signal_events.id (WATCHLIST_WARM or RECOMMENDATION_ELIGIBLE)")
    p.add_argument("--limit", type=int, default=DEFAULT_EVIDENCE_LIMIT, help="Number of evidence messages to include")
    p.add_argument("--demo", action="store_true", help="Run demo generation (no DB required)")
    p.add_argument("--force", action="store_true", help="Overwrite existing evidence bundle/markdown for this event_id (dev only)")

    args = p.parse_args()

    if args.demo or args.event_id is None:
        res = demo_generate(force=args.force)
    else:
        res = generate_from_db(args.event_id, evidence_limit=args.limit, force=args.force)

    # If res is a dict, print it. If it's a dataclass, print its __dict__.
    try:
        payload = res if isinstance(res, dict) else res.__dict__
    except Exception:
        payload = {"result": str(res)}

    print(json.dumps(payload, indent=2, default=_json_default))

