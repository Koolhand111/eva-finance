from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .hashutil import sha256_hex
from .render import render_markdown
from .sanitize import sanitize_text

GENERATOR_VERSION = os.getenv("EVA_WORKER_VERSION", "dev")
OUTPUT_ROOT = Path(os.getenv("EVA_RECO_OUTPUT_DIR", "eva_worker/output/recommendations"))

# Postgres connection env vars (match your existing worker patterns if different)
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "eva")
PG_USER = os.getenv("POSTGRES_USER", "eva")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

DEFAULT_EVIDENCE_DAYS = int(os.getenv("EVA_RECO_DEFAULT_EVIDENCE_DAYS", "7"))
DEFAULT_EVIDENCE_LIMIT = int(os.getenv("EVA_RECO_EVIDENCE_LIMIT", "50"))


@dataclass
class GenerationResult:
    markdown_path: str
    bundle_path: str
    bundle_sha256: str


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    out = []
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


def _write_gz_json(path: Path, payload: Dict[str, Any]) -> str:
    """
    Writes a gzipped JSON file. Returns SHA256 of the *uncompressed* JSON bytes.
    """
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    digest = sha256_hex(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(raw)
    return digest


def _ensure_append_only(path: Path) -> None:
    """
    Evidence bundles should be append-only. If a bundle already exists, refuse to overwrite.
    This prevents accidental history rewrites.
    """
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing evidence bundle: {path}")


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


def _load_from_db(event_id: int, evidence_limit: int) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Loads:
      - anchor event (RECOMMENDATION_ELIGIBLE)
      - confidence snapshot as-of event time
      - evidence items
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
                anchor_rows = _run_query(cur, anchor_sql, {"event_id": event_id})
                if not anchor_rows:
                    raise RuntimeError(f"No RECOMMENDATION_ELIGIBLE event found for id={event_id}")
                anchor = anchor_rows[0]

                # Determine evidence window
                event_time = anchor.get("event_time")
                window_start = anchor.get("window_start")
                window_end = anchor.get("window_end")

                # Derive a default window if missing
                if window_end is None:
                    window_end = event_time
                if window_start is None:
                    window_start = window_end - timedelta(days=DEFAULT_EVIDENCE_DAYS)

                anchor["window_start"] = window_start
                anchor["window_end"] = window_end

                entity_id = anchor.get("entity_id")
                if entity_id is None:
                    raise RuntimeError("Anchor event must include entity_id (or be joinable deterministically).")

                snapshot_rows = _run_query(cur, snapshot_sql, {"entity_id": entity_id, "event_time": event_time})
                snapshot = snapshot_rows[0] if snapshot_rows else None

                evidence_rows = _run_query(
                    cur,
                    evidence_sql,
                    {
                        "entity_id": entity_id,
                        "window_start": window_start,
                        "window_end": window_end,
                        "limit": evidence_limit,
                    },
                )

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
        items.append(
            {
                "processed_message_id": r.get("processed_message_id"),
                "raw_message_id": r.get("raw_message_id"),
                "created_at": (
                    r.get("created_at").astimezone(timezone.utc).isoformat()
                    if r.get("created_at") is not None
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


def generate_from_db(event_id: int, evidence_limit: int = DEFAULT_EVIDENCE_LIMIT) -> GenerationResult:
    """
    Main entrypoint (DB mode). Generates:
      - evidence bundle (.json.gz) [append-only]
      - recommendation markdown (.md)
    """
    anchor, snapshot, evidence_rows = _load_from_db(event_id, evidence_limit)

    entity_name = (anchor.get("entity_name") or "").strip() or "UNKNOWN"
    ticker = (anchor.get("ticker") or "").strip()
    entity_id = anchor.get("entity_id")

    event_time: datetime = anchor["event_time"]
    window_start: datetime = anchor["window_start"]
    window_end: datetime = anchor["window_end"]

    entity_slug = slugify(entity_name or ticker or f"entity-{entity_id or 'unknown'}")
    out_dir = OUTPUT_ROOT / entity_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build evidence items
    evidence_items = _build_evidence_items(evidence_rows)

    # Evidence bundle (canonical record)
    bundle = {
        "schema": "eva-finance-evidence-bundle",
        "schema_version": "v1.0",
        "anchor": {
            "signal_event_id": anchor.get("signal_event_id"),
            "event_type": anchor.get("event_type"),
            "event_time": event_time.astimezone(timezone.utc).isoformat(),
            "entity": {"entity_id": entity_id, "name": entity_name, "ticker": ticker or None},
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
    _ensure_append_only(bundle_path)
    bundle_sha = _write_gz_json(bundle_path, bundle)

    # Message IDs used for traceability
    message_ids_used: List[int] = []
    for it in evidence_items:
        mid = it.get("processed_message_id") or it.get("raw_message_id")
        if mid is not None:
            message_ids_used.append(int(mid))

    # Render Markdown
    md = render_markdown(
        schema_version="v1.0",
        generated_at_iso=datetime.now().astimezone().isoformat(),
        anchor={
            "signal_event_id": anchor.get("signal_event_id"),
            "event_type": anchor.get("event_type"),
            "event_time": event_time.isoformat(),
        },
        entity={
            "entity_id": entity_id,
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
            "confidence_snapshot_id": (snapshot or {}).get("id"),
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
    md_path.write_text(md, encoding="utf-8")

    return GenerationResult(str(md_path), str(bundle_path), bundle_sha)


def demo_generate() -> GenerationResult:
    """
    Demo mode (no DB): proves end-to-end artifact creation works.
    """
    now = datetime.now().astimezone()
    window_end = now
    window_start = now - timedelta(days=7)

    snapshot = {"id": 999, "score": 0.87, "phase": "ACCELERATION", "metrics": {"volume_z": 2.4, "sentiment_z": 1.9}}

    evidence_items = [
        {
            "processed_message_id": 101,
            "raw_message_id": 101,
            "created_at": now.astimezone(timezone.utc).isoformat(),
            "source": {"platform": "reddit", "subreddit": "MakeupAddiction", "permalink": "[link removed]"},
            "raw": {"text": "Everyone keeps recommending this brand lately — feels like it’s everywhere."},
            "sanitized": {"text": "Everyone keeps recommending this brand lately — feels like it’s everywhere."},
            "processed": {"sentiment": "positive", "intent": "evaluative", "tags": ["foundation"], "brand": ["DemoBrand"], "weight": 0.92},
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
            "entity": {"entity_id": 77, "name": "DemoBrand", "ticker": None},
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
    # For demo, allow overwrite (people re-run demos)
    bundle_sha = _write_gz_json(bundle_path, bundle)

    md = render_markdown(
        schema_version="v1.0",
        generated_at_iso=datetime.now().astimezone().isoformat(),
        anchor={"signal_event_id": 12345, "event_type": "RECOMMENDATION_ELIGIBLE", "event_time": now.isoformat()},
        entity={"entity_id": 77, "name": "DemoBrand", "ticker": "", "slug": entity_slug},
        source_window={"start": window_start.isoformat(), "end": window_end.isoformat()},
        evidence_meta={"bundle_path": str(bundle_path), "bundle_sha256": bundle_sha, "max_excerpts": 15, "max_chars_each": 400},
        reproducibility={"component": "eva_worker", "version": GENERATOR_VERSION, "confidence_snapshot_id": snapshot.get("id"), "message_ids_used": [101]},
        llm_meta={"used": False, "provider": None, "model": None, "prompt_sha256": None, "response_sha256": None},
        snapshot=snapshot,
        evidence_items=evidence_items,
    )

    md_path = out_dir / "12345_EVA-Finance_Recommendation.md"
    md_path.write_text(md, encoding="utf-8")

    return GenerationResult(str(md_path), str(bundle_path), bundle_sha)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Generate EVA-Finance Recommendation artifacts.")
    p.add_argument("--event-id", type=int, help="signal_events.id for RECOMMENDATION_ELIGIBLE")
    p.add_argument("--limit", type=int, default=DEFAULT_EVIDENCE_LIMIT, help="Number of evidence messages to include")
    p.add_argument("--demo", action="store_true", help="Run demo generation (no DB required)")

    args = p.parse_args()

    if args.demo or args.event_id is None:
        res = demo_generate()
    else:
        res = generate_from_db(args.event_id, evidence_limit=args.limit)

    print(json.dumps(res.__dict__, indent=2))
