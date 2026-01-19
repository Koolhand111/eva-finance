=== EVA-Finance Engineering Continuation Snapshot ===

PROJECT PURPOSE

EVA-Finance is a deterministic behavioral signal analysis system that extracts consumer brand sentiment from Reddit conversational data, scores signals using multi-factor confidence metrics, and generates trading recommendations validated through paper trading. The system transforms raw social mentions into actionable investment signals by detecting brand-switch patterns, sentiment shifts, and share-of-voice changes.

**In-scope:**
- Reddit ingestion (BuyItForLife, Frugal, running, fashion subreddits)
- LLM-based extraction (GPT-4o-mini) with fallback heuristics
- Multi-factor confidence scoring (acceleration, intent, spread, baseline, suppression)
- Paper trading validation (Phase 0: 12-week trial, Jan-Mar 2026)
- Brand-to-ticker mapping via FMP API
- Notification delivery via ntfy

**Out-of-scope:**
- Live trading execution
- Non-Reddit data sources (Twitter, news)
- Cryptocurrency or forex signals
- User-facing frontend

MENTAL MODEL / EXECUTION ASSUMPTIONS

- All database access MUST use `eva_common.db.get_connection()` context manager (connection pooling)
- All configuration MUST come from `eva_common.config` Pydantic settings (never hardcode credentials)
- Brand mapping is NON-BLOCKING: FMP API failures do not crash the pipeline
- LLM extraction has FALLBACK: if OpenAI unavailable, deterministic heuristics kick in
- Signal deduplication via UNIQUE constraints and ON CONFLICT DO NOTHING
- Privacy: user IDs are hashed, no PII in logs, UTC timestamps only
- AI infrastructure worker is DISABLED by default (kill switch: `AI_INFRA_ENABLED=false`)
- Paper trading uses $1000 position size per trade, 15% profit target, -10% stop loss, 90-day max hold
- FMP API uses `/stable/search-name` endpoint (v3/search is deprecated since Aug 2025)
- Environment variables use POSTGRES_* prefix (not DB_*) for database config

CURRENT ARCHITECTURE

**Ingest sources:**
- eva-ingest-reddit: Fetches from 8 subreddits every 15 minutes via Reddit public JSON API
- n8n: External workflow automation (port 5678) posts to eva-api intake
- eva-ai-infrastructure-worker: Isolated AI subreddit ingestion (disabled by default)

**Processing pipeline:**
1. Raw messages → `raw_messages` table (via eva-api POST /intake/message)
2. eva-worker polls unprocessed rows every 10 seconds
3. `brain_extract()` calls GPT-4o-mini or fallback heuristics
4. Results → `processed_messages` table (brand[], tags[], sentiment, intent)
5. `emit_trigger_events()` queries trigger views, inserts `signal_events`
6. `poll_and_notify()` sends approved recommendations via ntfy
7. `ensure_brands_mapped()` batch-maps brands to tickers (non-blocking)

**Workers / schedulers:**
- eva-worker: Main processing loop (10s interval), notification polling (60s interval)
- eva-ingest-reddit: Reddit fetcher (15min loop)
- eva-ai-infrastructure-worker: AI subreddit ingestion (disabled)
- Cron: Paper trade updater (weekdays 4:30 PM ET), entry check (Saturdays 10 AM ET)

**Persistence layer (key tables):**
- `raw_messages`: Ingested text with source, platform_id, meta JSONB
- `processed_messages`: Extracted brand[], tags[], sentiment, intent
- `signal_events`: TAG_ELEVATED, BRAND_DIVERGENCE events
- `behavior_states`: Tag state tracking (NORMAL/ELEVATED)
- `eva_confidence_v1`: Multi-factor confidence scores
- `brand_ticker_mapping`: Brand-to-ticker resolution with materiality flag (27 mappings)
- `paper_trades`: Position tracking (entry, current price, exit conditions)

**Output artifacts:**
- Signal events in `signal_events` table
- Recommendations in `recommendation_drafts` table
- Paper trades in `paper_trades` table
- Notifications via ntfy (port 8085)

WHAT IS WORKING (END-TO-END)

- Reddit ingestion → raw_messages insertion (deterministic, idempotent)
- LLM extraction with fallback heuristics → processed_messages
- Trigger event emission (TAG_ELEVATED, BRAND_DIVERGENCE)
- Confidence scoring (eva_confidence_v1.py)
- Notification polling and delivery via ntfy
- Paper trade entry from approved signals
- Paper trade price updates and exit condition checking
- Brand-ticker lookup from `brand_ticker_mapping` table (27 existing mappings)
- Centralized config via `eva_common.config` (all services migrated)
- Connection pooling via `eva_common.db` (ThreadedConnectionPool)
- brand_research.py CLI tool (`--list-unmapped` works, manual mapping works)
- FMP API integration for auto-mapping (stable endpoint working)

WHAT IS PARTIALLY WORKING

- **Brand-to-ticker auto-mapping**: FMP API integration works, but searches company names not brand names. "Duluth Trading" → no results (needs "Duluth"), "MAC Cosmetics" → no results (subsidiary of Estée Lauder). Correctly logs for manual review via `v_unmapped_brands` view.
- **Google Trends validation**: Integration exists but requires manual review of boost/penalty thresholds
- **AI infrastructure worker**: Code complete and tested, but disabled by default (kill switch)
- **Recommendation generation**: Pipeline exists but approval criteria need tuning

KNOWN ISSUES / BUGS

- FMP API `search-name` endpoint searches company names, not brand names. Subsidiary brands (MAC → EL, Covergirl → COTY) require manual mapping.
- v_unmapped_brands view required DROP/CREATE due to schema mismatch with earlier test version
- Default password in docker-compose (`eva_password_change_me`) should be rotated for production
- Test artifacts in brand_ticker_mapping table (Duluth Trading, MAC Cosmetics marked as private incorrectly)

CURRENT FOCAL PROBLEM

Brand-ticker auto-mapping has limited coverage because FMP API searches official company names, not consumer brand names. This means subsidiary brands and brands with different trading names must be manually mapped. The system correctly logs these for manual review via `v_unmapped_brands` view (showing Jordan, Osprey, Patagonia, Uniqlo as top unmapped brands), but the automation only handles pure-play companies where brand name matches company name.

RECENT CHANGES

**Session: January 19, 2026**
- Created `brand_mapper_service.py` with FMP API integration
- Created migration `009_brand_ticker_mapping.sql` (table + views)
- Integrated brand mapping into worker.py (non-blocking batch processing)
- Fixed FMP API endpoint: `/api/v3/search` → `/stable/search-name` (legacy deprecated)
- Fixed brand_research.py to use `eva_common.db.get_connection()` (was using wrong env vars DB_* instead of POSTGRES_*)
- Moved test_brand_mapper.py to correct location (`eva_worker/eva_worker/`)
- Added FMP_API_KEY to docker-compose.yml eva-worker environment
- Added FMP settings to eva_common/config.py (fmp_api_key, fmp_enabled, fmp_rate_limit_ms)

**Uncommitted files:**
- `db/migrations/009_brand_ticker_mapping.sql` (NEW)
- `eva_worker/eva_worker/brand_mapper_service.py` (NEW)
- `eva_worker/eva_worker/test_brand_mapper.py` (NEW)
- `eva_worker/worker.py` (MODIFIED - brand mapper integration)
- `eva_worker/brand_research.py` (MODIFIED - uses eva_common.db)
- `eva_common/config.py` (MODIFIED - FMP settings)
- `docker-compose.yml` (MODIFIED - FMP_API_KEY)

NEXT STEPS (ORDERED)

1. Commit brand-ticker mapping changes (migration 009, service, worker integration)
2. Manually map high-signal brands from `v_unmapped_brands` view (Jordan→NKE, Osprey→private, Uniqlo→FRCOY, etc.)
3. Clean up test artifacts in brand_ticker_mapping (Duluth Trading should be DLTH not private)
4. Build Metabase dashboard for Phase 0 validation metrics (win rate, avg return, position count)
5. Review and tune confidence scoring thresholds based on paper trade performance

INVARIANTS / RULES

- Never hardcode database credentials (use eva_common.config)
- Never use psycopg2 directly (use eva_common.db.get_connection context manager)
- Never block pipeline on external API failures (brand mapping, Google Trends)
- Never log PII (hash user IDs, no names/emails)
- Financial amounts as integers (cents, not floats)
- UTC timestamps only
- Signal deduplication via database constraints (ON CONFLICT DO NOTHING)
- AI infrastructure worker must remain disabled unless explicitly enabled
- Paper trading exit rules immutable for Phase 0: 90 days OR +15% OR -10%

KEY FILE LOCATIONS

```
eva_common/config.py              # Pydantic settings (DB, OpenAI, FMP, Google Trends)
eva_common/db.py                  # Connection pooling (get_connection context manager)
eva_worker/worker.py              # Main processing loop (brain_extract, emit_trigger_events)
eva_worker/eva_worker/brand_mapper_service.py   # FMP API integration (NEW)
eva_worker/eva_worker/notify.py   # Notification polling and paper trade triggering
eva_worker/brand_research.py      # CLI tool for manual brand mapping
eva_worker/eva_confidence_v1.py   # Confidence scoring computation
scripts/paper_trading/paper_trade_entry.py      # Paper trade creation
db/migrations/009_brand_ticker_mapping.sql      # Brand mapping schema (NEW)
db/init.sql                       # Core schema
docker-compose.yml                # Service orchestration
.env                              # Secrets (OPENAI_API_KEY, FMP_API_KEY, DB creds)
```

QUICK START (RESTORE CONTEXT)

```bash
# Verify system health
docker compose ps
docker exec eva_worker python -c "from eva_common.db import get_connection; print('DB OK')"
docker exec eva_db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM brand_ticker_mapping;"

# Check brand mapping service
docker exec eva_worker python -m eva_worker.test_brand_mapper

# List unmapped brands needing research
docker exec eva_worker python /app/brand_research.py --list-unmapped

# Add a brand mapping manually
docker exec eva_worker python /app/brand_research.py "Jordan" "NKE" --parent "Nike Inc" --material --exchange NYSE

# Check worker logs for brand mapping activity
docker compose logs eva-worker --tail=50 | grep -i brand

# Query recent mappings
docker exec eva_db psql -U eva -d eva_finance -c "SELECT brand, ticker, material FROM brand_ticker_mapping ORDER BY updated_at DESC LIMIT 10;"

# Rebuild and restart worker after changes
docker compose build eva-worker && docker compose up -d eva-worker
```

ENVIRONMENT

- **OS:** Linux 6.8.0-90-generic (Ubuntu)
- **Runtime:** Python 3.12-slim (Docker containers)
- **Database:** PostgreSQL 16 (container: eva_db)
- **Services:**
  - eva_db: postgres:16 (internal 5432)
  - eva_api: FastAPI on port 9080
  - eva_worker: background processing (no port)
  - eva_ntfy: ntfy on port 8085
  - metabase: port 3000
  - n8n: port 5678 (external, connected to eva_net)
- **External APIs:**
  - OpenAI: GPT-4o-mini for extraction
  - FMP: Financial Modeling Prep for ticker lookup (stable API)
  - Reddit: Public JSON API (no auth required)

STATUS

System operational. Brand-ticker auto-mapping service deployed and tested. FMP API integration working with stable endpoint. Manual mapping required for subsidiary brands. 27 brands mapped, 20+ high-signal brands awaiting manual research. Ready to commit changes and expand brand coverage.

LAST UPDATED

2026-01-19
