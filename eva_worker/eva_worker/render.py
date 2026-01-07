from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .sanitize import sanitize_text


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _yaml_quote(s: str) -> str:
    """Simple YAML-safe quoting for scalar strings."""
    s = (s or "").replace('"', '\\"')
    return f'"{s}"'


def render_markdown(
    *,
    schema_version: str,
    generated_at_iso: str,
    anchor: Dict[str, Any],
    entity: Dict[str, Any],
    source_window: Dict[str, Any],
    evidence_meta: Dict[str, Any],
    reproducibility: Dict[str, Any],
    llm_meta: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]],
    evidence_items: List[Dict[str, Any]],
    excerpt_max: int = 15,
    excerpt_chars: int = 400,
) -> str:
    """
    Render the EVA-Finance Recommendation Markdown artifact.

    This file is designed to be:
      - calm and non-hypey
      - auditable (front matter includes hashes + IDs)
      - traceable (excerpts cite message IDs)
      - separable: AUTO sections are prefilled, HUMAN sections are placeholders
    """

    # Snapshot-derived headline values (schema v1: final_confidence + band)
    confidence = None
    band = None
    if snapshot:
        confidence = snapshot.get("final_confidence") or snapshot.get("confidence_score") or snapshot.get("score")
        band = snapshot.get("band") or snapshot.get("phase")

    # Build sanitized excerpts list (Markdown)
    excerpts_md: List[str] = []
    for item in evidence_items[:excerpt_max]:
        src = item.get("source", {}) or {}
        sub = src.get("subreddit") or "unknown"
        ts = item.get("created_at") or ""
        mid = item.get("processed_message_id") or item.get("raw_message_id")

        raw_text = ((item.get("raw", {}) or {}).get("text")) or ""
        safe = sanitize_text(raw_text, sanitize_urls=True, sanitize_usernames=True)
        safe = _clip(safe, excerpt_chars)

        processed = item.get("processed", {}) or {}
        weight = processed.get("weight")
        intent = processed.get("intent")
        sentiment = processed.get("sentiment")

        excerpts_md.append(
            f"- `#{mid} | r/{sub} | {ts}`\n"
            f"  > {safe}\n"
            f"  *Weight:* {weight} | *Intent:* {intent} | *Sentiment:* {sentiment}\n"
        )

    # Front matter fields
    # NOTE: keep this stable; downstream tools can parse YAML for dashboards/post-mortems.
    front_matter = f"""---
schema: eva-finance-recommendation
schema_version: {schema_version}
generated_at: {generated_at_iso}

anchor:
  signal_event_id: {anchor.get("signal_event_id")}
  event_type: {_yaml_quote(anchor.get("event_type", ""))}
  event_time: {_yaml_quote(anchor.get("event_time", ""))}

entity:
  entity_key: {_yaml_quote(entity.get("entity_key", ""))}
  name: {_yaml_quote(entity.get("name", ""))}
  ticker: {_yaml_quote(entity.get("ticker", ""))}
  slug: {_yaml_quote(entity.get("slug", ""))}

source_window:
  start: {_yaml_quote(source_window.get("start", ""))}
  end: {_yaml_quote(source_window.get("end", ""))}

evidence:
  bundle_path: {_yaml_quote(evidence_meta.get("bundle_path", ""))}
  bundle_sha256: {_yaml_quote(evidence_meta.get("bundle_sha256", ""))}
  excerpt_policy:
    max_excerpts: {evidence_meta.get("max_excerpts", excerpt_max)}
    max_chars_each: {evidence_meta.get("max_chars_each", excerpt_chars)}
    sanitize_usernames: true
    sanitize_urls: true

reproducibility:
  generator:
    component: {_yaml_quote(reproducibility.get("component", "eva_worker"))}
    version: {_yaml_quote(reproducibility.get("version", "dev"))}
  db_snapshot:
    confidence_snapshot_id: {reproducibility.get("confidence_snapshot_id")}
    message_ids_used: {reproducibility.get("message_ids_used", [])}

llm:
  used: {str(llm_meta.get("used", False)).lower()}
  provider: {_yaml_quote(llm_meta.get("provider")) if llm_meta.get("provider") else "null"}
  model: {_yaml_quote(llm_meta.get("model")) if llm_meta.get("model") else "null"}
  prompt_sha256: {_yaml_quote(llm_meta.get("prompt_sha256")) if llm_meta.get("prompt_sha256") else "null"}
  response_sha256: {_yaml_quote(llm_meta.get("response_sha256")) if llm_meta.get("response_sha256") else "null"}
---
"""

    # Body: keep calm, machine-filled where appropriate, human sections clearly marked.
    body = f"""
# EVA-Finance Recommendation

---

## 1. Executive Assessment (Read This First)

**Recommendation:** Candidate for upward trajectory
**Confidence Level:** {confidence if confidence is not None else "UNKNOWN"}
**Signal Phase:** {band if band else "UNKNOWN"}
**Signal Initiation Date:** {anchor.get("event_time", "")[:10]}

**Summary (AUTO Draft):**
- [AUTO] EVA detected a threshold crossing for **{entity.get("name", "UNKNOWN")}**.
- [AUTO] Evidence bundle archived for post-mortem integrity (see front matter).
- [AUTO] This is not advice; it’s a pattern snapshot.

---

## 2. Why This Company (HUMAN)

**Core Thesis (Plain Language):**
[Write your thesis here.]

**Machine Notes (AUTO):**
- [AUTO] Add theme clusters here (optional LLM-assisted in v1.1).
- [AUTO] Keep it calm and cite evidence IDs.

---

## 3. Why Now (Timing Justification)

**Interpretation (AUTO Draft):**
- [AUTO] Reference snapshot deltas + spread + intent progression.
- [AUTO] If you can’t write this clearly, recommendation shouldn’t exist.

---

## 4. Signal Evidence

### Evidence Excerpts (AUTO, sanitized)
{chr(10).join(excerpts_md) if excerpts_md else "- (No evidence items selected)"}

---

## 5. Comparative Context (Why This, Not Others)

[AUTO: cohort ranking + rejections go here once cohort/gates are wired.]

---

## 6. Risks & Disconfirming Signals

**Known Risks (HUMAN):**
- [Add risks here.]

**Signals That Would Weaken This Recommendation (AUTO):**
- Intent regression (evaluative/action → exploratory)
- Volume spike without sentiment stabilization
- Single-community concentration

---

## 7. Confidence Interpretation

**Confidence Score:** {confidence if confidence is not None else "UNKNOWN"}

This score reflects EVA's confidence that the pattern is materially different from noise,
not certainty of outcome.

---

## 8. Post-Recommendation Tracking

**Review Windows:**
- 30 days
- 90 days
- 180 days

**Post-Mortem Required:** Yes  
**Outcome Classification:** Pending

---

## 9. Final Note

EVA issues recommendations infrequently by design.
This artifact is a threshold crossing snapshot — not a verdict.
"""
    return (front_matter + body).strip() + "\n"
