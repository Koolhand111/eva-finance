=== EVA-Finance Engineering Continuation Snapshot ===

PROJECT PURPOSE

EVA-Finance detects early behavioral trend signals by analyzing conversational data from social platforms. It extracts brand mentions, behavioral tags (comfort, brand-switch), and sentiment/intent using LLM-powered extraction. Confidence scoring identifies high-signal brand-tag pairs for tracking. In-scope: ingest, extraction, scoring, signal detection, notification drafts. Out-of-scope: automated trading, product recommendations, ticker forecasting, production-scale ingestion infrastructure.

MENTAL MODEL / EXECUTION ASSUMPTIONS

- Tags represent behaviors (comfort, brand-switch, running), not products
- Brand flow models switching pressure (multi-brand signals more valuable than single-brand)
- Confidence is multi-factor (acceleration, intent, spread, baseline, suppression), not binary
- LLM extraction first, heuristic fallback second (never block pipeline)
- Prefer false negatives over false positives (strict gates: intent ≥0.65, suppression ≥0.50, spread ≥0.50)
- Persistence > spike magnitude (1-day wonders get penalized)
- Evidence bundles are append-only (no rewrites, SHA256-verified)
- Notification requires human approval (recommendation_drafts.notify_ready gate)
- Docker-first local environment (postgres, eva-api, eva-worker, metabase, ntfy)

CURRENT ARCHITECTURE

Ingest sources:
- Manual insertion via eva-api POST /intake/message
- Future: n8n workflows (Reddit, Twitter, etc.)

Processing pipeline:
- raw_messages → worker.py process_batch() → brain_extract() (LLM/fallback) → processed_messages
- worker.py emit_trigger_events() → signal_events (TAG_ELEVATED, BRAND_DIVERGENCE)
- eva_confidence_v1.py → eva_confidence_v1 table (daily scoring) → signal_events (RECOMMENDATION_ELIGIBLE, WATCHLIST_WARM)
- eva_worker/eva_worker/generate.py → recommendation_drafts + artifacts (.json.gz bundle, .md recommendation)

Workers / schedulers:
- eva-worker container: runs worker.py (10s poll loop, LLM extraction + trigger emission)
- Manual: python eva_confidence_v1.py (scores daily candidates, emits RECOMMENDATION_ELIGIBLE if band=HIGH)
- Manual: python -m eva_worker.eva_worker.generate --event-id <id> (generates recommendation artifacts)

Persistence layer (key tables):
- raw_messages: platform posts/comments (processed flag)
- processed_messages: extracted brand[], tags[], sentiment, intent
- signal_events: trigger/scoring events (TAG_ELEVATED, BRAND_DIVERGENCE, RECOMMENDATION_ELIGIBLE, WATCHLIST_WARM)
- behavior_states: tag-level state tracking (NORMAL, ELEVATED)
- eva_confidence_v1: daily brand+tag confidence scores (acceleration, intent, spread, baseline, suppression → final_confidence, band)
- recommendation_drafts: human-approval gate for notifications (notify_ready, approved_at, notify_attempts, last_notify_error)

Output artifacts:
- eva_worker/output/recommendations/<brand_slug>/<event_id>_evidence.json.gz (canonical evidence bundle)
- eva_worker/output/recommendations/<brand_slug>/<event_id>_EVA-Finance_Recommendation.md (human-readable report)

WHAT IS WORKING (END-TO-END)

- Docker compose up: postgres, eva-api, eva-worker, metabase, ntfy
- Manual message insert via curl → eva-api → raw_messages
- worker.py automatic extraction (LLM + heuristic fallback) → processed_messages
- worker.py trigger emission (TAG_ELEVATED, BRAND_DIVERGENCE) → signal_events
- Manual eva_confidence_v1.py scoring → eva_confidence_v1 table + RECOMMENDATION_ELIGIBLE events
- Manual generate.py --event-id <id> → evidence bundle + markdown recommendation + recommendation_drafts record
- Automatic recommendation_drafts insertion after artifact creation (idempotent via ON CONFLICT)
- DB schema migrations (init.sql, 002_add_notification_approval.sql)

WHAT IS PARTIALLY WORKING

- n8n workflows exist (eva_worker/n8n.json) but not deployed/tested
- n8n notification polling queries (db/migrations/n8n_notification_queries.sql) defined but not integrated
- ntfy container running but no automated notifications wired up
- Retry logic for failed notifications (notify_attempts, last_notify_error) defined but not tested

KNOWN ISSUES / BUGS

- eva_confidence_v1.py hardcoded to score only current_date candidates (misses multi-day accumulation)
- n8n notification polling not yet integrated with recommendation_drafts table

CURRENT FOCAL PROBLEM

Auto-insertion into recommendation_drafts complete. generate.py now automatically creates recommendation_drafts records after artifact generation (idempotent via ON CONFLICT). Next focus: integrate n8n notification polling workflow to query recommendation_drafts.notify_ready=true and send notifications via ntfy.

RECENT CHANGES

Last commit (886a7ce): Update context snapshot after package structure commit
- Updated EVA_CONTEXT_SNAPSHOT.md with completed package structure cleanup
- Marked package structure and container verification as complete

Current uncommitted work:
- Modified eva_worker/eva_worker/generate.py: added _insert_recommendation_draft() function
- Auto-insertion into recommendation_drafts after artifact creation (idempotent via ON CONFLICT)
- Returns draft_id in generate_from_db() response
- Tested end-to-end: artifacts + draft creation verified working
- Container rebuilt and restarted with updated code

NEXT STEPS (ORDERED)

1. ✅ COMPLETE: Commit package structure changes (commit 0829675)
2. ✅ COMPLETE: Verify container works after restructure (container running, Python 3.12.12, dependencies OK)
3. ✅ COMPLETE: Wire generate.py output to auto-insert recommendation_drafts row after artifact creation
4. Test n8n workflow import (eva_worker/n8n.json) and notification polling queries
5. Integrate n8n notification polling with recommendation_drafts table
6. Test ntfy notification delivery end-to-end
7. Consider migrating legacy worker.py/scoring.py/eva_confidence_v1.py into eva_worker/eva_worker/ package (optional cleanup)

INVARIANTS / RULES

- Evidence bundles (.json.gz) are append-only (no overwrites unless --force in dev)
- recommendation_drafts.notified_at cannot be set unless notify_ready = true (DB constraint chk_notify_requires_approval)
- Confidence gates must remain strict (intent ≥0.65, suppression ≥0.50, spread ≥0.50) to avoid noise
- Never skip LLM fallback (fallback_brain_extract must always succeed)
- Tags must be behavior-first (comfort, brand-switch, running), not product names
- Multi-brand signals (len(brand) ≥2) + switch/comparative language → enforce brand-switch tag + intent=own

KEY FILE LOCATIONS

- db/init.sql (schema: tables, views, indexes, functions)
- db/migrations/002_add_notification_approval.sql (recommendation_drafts table, approval gates)
- eva_worker/worker.py (root, stale but currently running in container)
- eva_worker/eva_confidence_v1.py (root, stale but manual scoring still uses it)
- eva_worker/eva_worker/generate.py (new package, artifact generation)
- eva_worker/eva_worker/render.py (markdown template rendering)
- eva_worker/eva_worker/sanitize.py (PII/URL sanitization)
- eva_worker/eva_worker/hashutil.py (SHA256 utilities)
- eva-api/app.py (FastAPI: /intake/message, /events, /events/<id>/ack)
- docker-compose.yml (service definitions: db, eva-api, eva-worker, metabase, ntfy)
- Project_Map.md (design decisions, key concepts)

QUICK START (RESTORE CONTEXT)

Verify system health:
```bash
docker compose ps
curl http://localhost:9080/health
psql postgres://eva:eva_password_change_me@localhost:5432/eva_finance -c "SELECT COUNT(*) FROM raw_messages;"
```

Run critical manual steps:
```bash
# Ingest test message
curl -X POST http://localhost:9080/intake/message -H "Content-Type: application/json" -d '{"source":"reddit","timestamp":"2025-01-06T12:00:00Z","text":"Switched from Nike to Hoka for running. Way more comfortable."}'

# Wait 10s for worker to process, then score
docker exec -it eva_worker python eva_confidence_v1.py

# Check signal events
psql postgres://eva:eva_password_change_me@localhost:5432/eva_finance -c "SELECT * FROM signal_events ORDER BY id DESC LIMIT 5;"

# Generate recommendation for event_id (if RECOMMENDATION_ELIGIBLE exists)
docker exec -it eva_worker python -m eva_worker.eva_worker.generate --event-id <event_id>
```

Inspect current state:
```bash
docker compose logs eva_worker --tail 50
psql postgres://eva:eva_password_change_me@localhost:5432/eva_finance -c "SELECT COUNT(*) FROM processed_messages WHERE processor_version LIKE 'llm:%';"
ls -lh eva_worker/output/recommendations/
```

ENVIRONMENT

- OS: Linux (kernel 6.8.0-90-generic)
- Runtime: Python 3.12, postgres:16, Docker Compose
- Services:
  - db (postgres:16): internal 5432
  - eva-api (FastAPI): 0.0.0.0:9080
  - eva-worker (Python): no exposed ports
  - metabase: 0.0.0.0:3000
  - ntfy: 0.0.0.0:8085
- Ports: 9080 (API), 3000 (Metabase), 8085 (ntfy)
- External dependencies: OpenAI API (gpt-4o-mini for LLM extraction, optional)

STATUS

Docker services running. DB schema complete. Package structure committed (dual structure: legacy root + new package). Container verified working (Python 3.12.12, dependencies OK). Worker extracting and emitting triggers. Scoring and recommendation generation manual. Notification pipeline defined but not wired. Next: auto-insert recommendation_drafts after generation.

LAST UPDATED

2026-01-07 (post-commit 0829675, container verified)
