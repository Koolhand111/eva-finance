---
schema: eva-finance-recommendation
schema_version: v1.0
generated_at: 2026-01-05T18:24:11.785697+00:00

anchor:
  signal_event_id: 12345
  event_type: "RECOMMENDATION_ELIGIBLE"
  event_time: "2026-01-05T13:24:11.785302-05:00"

entity:
  entity_key: "DemoBrand"
  name: "DemoBrand"
  ticker: ""
  slug: "demobrand"

source_window:
  start: "2025-12-29T13:24:11.785302-05:00"
  end: "2026-01-05T13:24:11.785302-05:00"

evidence:
  bundle_path: "eva_worker/output/recommendations/demobrand/12345_evidence.json.gz"
  bundle_sha256: "2f48d56c4cdbbc42a7189493645d3cb81935ef5dbbfa5916e9fbebe898670fec"
  excerpt_policy:
    max_excerpts: 15
    max_chars_each: 400
    sanitize_usernames: true
    sanitize_urls: true

reproducibility:
  generator:
    component: "eva_worker"
    version: "dev"
  db_snapshot:
    confidence_snapshot_id: 999
    message_ids_used: [101]

llm:
  used: false
  provider: null
  model: null
  prompt_sha256: null
  response_sha256: null
---

# EVA-Finance Recommendation

---

## 1. Executive Assessment (Read This First)

**Recommendation:** Candidate for upward trajectory
**Confidence Level:** 0.87
**Signal Phase:** HIGH
**Signal Initiation Date:** 2026-01-05

**Summary (AUTO Draft):**
- [AUTO] EVA detected a threshold crossing for **DemoBrand**.
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
- `#101 | r/MakeupAddiction | 2026-01-05T18:24:11.785302+00:00`
  > Everyone keeps recommending this brand lately — feels like it’s everywhere.
  *Weight:* 0.92 | *Intent:* evaluative | *Sentiment:* positive


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

**Confidence Score:** 0.87

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
