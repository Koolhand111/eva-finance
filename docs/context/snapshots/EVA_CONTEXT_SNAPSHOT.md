=== EVA-Finance Engineering Continuation Snapshot ===

PROJECT PURPOSE

EVA-Finance is a deterministic behavioral signal analysis system that extracts consumer brand sentiment from Reddit conversational data, scores signals using multi-factor confidence metrics, and generates trading recommendations validated through paper trading. The system transforms raw social mentions into actionable investment signals by detecting brand-switch patterns, sentiment shifts, and share-of-voice changes.

**In-scope:**
- Reddit ingestion (BuyItForLife, Frugal, running, malefashionadvice, femalefashionadvice, goodyearwelt, onebag, sneakers)
- LLM-based extraction (GPT-4o-mini) with fallback heuristics
- Multi-factor confidence scoring (acceleration, intent, spread, baseline, suppression)
- Google Trends cross-validation of high-confidence signals
- Paper trading validation (Phase 0: 12-week trial, Jan-Mar 2026)
- Brand-to-ticker mapping via FMP API
- Notification delivery via ntfy

**Out-of-scope:**
- Live trading execution
- Non-Reddit data sources (Twitter, news)
- Cryptocurrency or forex signals
- User-facing frontend

MENTAL MODEL / EXECUTION ASSUMPTIONS

- All database access MUST use `eva_common.db.get_connection()` context manager (connection pooling via ThreadedConnectionPool)
- All configuration MUST come from `eva_common.config` Pydantic settings (never hardcode credentials)
- Brand mapping is NON-BLOCKING: FMP API failures do not crash the pipeline
- Google Trends validation is NON-BLOCKING: rate-limited requests return `validation_status='pending'` and do not alter confidence scores
- LLM extraction has FALLBACK: if OpenAI unavailable, deterministic heuristics kick in
- Signal deduplication via UNIQUE constraints and ON CONFLICT DO NOTHING
- Privacy: user IDs are hashed, no PII in logs, UTC timestamps only
- AI infrastructure worker is ENABLED in docker-compose (`AI_INFRA_ENABLED=true`) but has a kill switch
- Paper trading uses $1000 position size per trade, 15% profit target, -10% stop loss, 90-day max hold
- FMP API uses `/stable/search-name` endpoint (v3/search is deprecated since Aug 2025)
- Environment variables use POSTGRES_* prefix (not DB_*) for database config in eva_common; paper trading scripts use DB_* prefix with defaults
- PostgreSQL port 5432 is exposed to host for local tooling (Exit Sentinel, etc.)
- `eva_confidence_v1.py` still uses direct `psycopg2.connect()` instead of `eva_common.db.get_connection()` — known deviation, migration pending
- Confidence scoring thresholds are adaptive for Phase 0 (lowered from production values) and configurable via env vars (EVA_GATE_*, EVA_BAND_*)
- Worker polls unprocessed rows every 10 seconds; notification polling every 60 seconds
- Google Trends exponential backoff: 5s base delay, 120s max delay, 3 retries with session reset between attempts

CURRENT ARCHITECTURE

**Ingest sources:**
- eva-ingest-reddit: Fetches from 8 subreddits every 15 minutes via Reddit public JSON API (BuyItForLife, Frugal, running, malefashionadvice, femalefashionadvice, goodyearwelt, onebag, sneakers)
- n8n: External workflow automation (port 5678) posts to eva-api intake
- eva-ai-infrastructure-worker: Isolated AI subreddit ingestion (networking, selfhosted, semiconductors)

**Processing pipeline:**
1. Raw messages → `raw_messages` table (via eva-api POST /intake/message)
2. eva-worker polls unprocessed rows every 10 seconds (`process_batch(limit=20)`)
3. `brain_extract()` calls GPT-4o-mini or fallback heuristics
4. Results → `processed_messages` table (brand[], tags[], sentiment, intent)
5. `emit_trigger_events()` queries trigger views, inserts `signal_events`
6. `poll_and_notify()` sends approved recommendations via ntfy (60s interval)
7. `ensure_brands_mapped()` batch-maps brands to tickers (non-blocking)
8. `eva_confidence_v1.py` scores candidates from `v_eva_candidate_brand_signals_v1` view
9. Google Trends validation applied to HIGH-band signals above min confidence threshold (0.60)

**Workers / schedulers:**
- eva-worker: Main processing loop (10s interval), notification polling (60s interval)
- eva-ingest-reddit: Reddit fetcher (15min loop, 8 subreddits, 25 posts per sub)
- eva-ai-infrastructure-worker: AI subreddit ingestion (enabled, networking/selfhosted/semiconductors)
- Cron: Paper trade price updater (weekdays 4:00 PM ET), exit checker (weekdays 4:00 PM ET after price update)

**Persistence layer (key tables):**
- `raw_messages`: Ingested text with source, platform_id, meta JSONB
- `processed_messages`: Extracted brand[], tags[], sentiment, intent
- `signal_events`: TAG_ELEVATED, BRAND_DIVERGENCE, WATCHLIST_WARM, RECOMMENDATION_ELIGIBLE events
- `behavior_states`: Tag state tracking (NORMAL/ELEVATED)
- `eva_confidence_v1`: Multi-factor confidence scores with details JSONB (includes google_trends data)
- `brand_ticker_mapping`: Brand-to-ticker resolution with materiality flag
- `paper_trades`: Position tracking (entry, current price, exit conditions, return_pct, return_dollar)
- `google_trends_validation`: Validation results per brand (search_interest, trend_direction, confidence_boost)

**Key views:**
- `v_trigger_tag_elevated`: Tags in ELEVATED state within last day
- `v_trigger_brand_divergence`: Brands with >=5% share-of-voice delta in last 7 days
- `v_eva_candidate_brand_signals_v1`: Candidate signals for confidence scoring (min 2 messages)
- `v_daily_brand_tag_stats`: Daily aggregated stats per brand+tag
- `v_brand_tag_daily_summary`: Summarized daily metrics per brand+tag
- `v_paper_trading_performance`: Paper trading performance stats

**Output artifacts:**
- Signal events in `signal_events` table
- Confidence scores in `eva_confidence_v1` table
- Paper trades in `paper_trades` table
- Notifications via ntfy (port 8085)
- Metabase dashboards (port 3000)

WHAT IS WORKING (END-TO-END)

- Reddit ingestion → raw_messages insertion (deterministic, idempotent)
- LLM extraction with fallback heuristics → processed_messages
- Trigger event emission (TAG_ELEVATED, BRAND_DIVERGENCE)
- Confidence scoring (eva_confidence_v1.py) with WATCHLIST_WARM and RECOMMENDATION_ELIGIBLE events
- Notification polling and delivery via ntfy
- Paper trade entry from approved signals
- Paper trade price updates and exit condition checking
- Brand-ticker lookup from `brand_ticker_mapping` table
- Centralized config via `eva_common.config` (all services migrated)
- Connection pooling via `eva_common.db` (ThreadedConnectionPool)
- brand_research.py CLI tool (`--list-unmapped` works, manual mapping works)
- FMP API integration for auto-mapping (stable endpoint working)
- AI infrastructure worker ingesting from networking/selfhosted/semiconductors subreddits
- Google Trends non-blocking validation with exponential backoff and retry logic

WHAT IS PARTIALLY WORKING

- **Google Trends validation**: Rate limiting hardened with exponential backoff (5s base, 120s max), retry logic (3 retries), session reset, and non-blocking mode. Integration works but rate limits from Google are frequent. Pending requests skip confidence adjustment. Boost/penalty thresholds need tuning against real signal outcomes.
- **Brand-to-ticker auto-mapping**: FMP API integration works, but `search-name` searches company names not brand names. Subsidiary brands (MAC → EL, Covergirl → COTY) require manual mapping.
- **Recommendation generation**: Pipeline exists but approval criteria need tuning
- **Confidence scoring thresholds**: Phase 0 adaptive thresholds lowered for early data validation, need review as data volume grows
- **Skills directory**: New `skills/eva-finance/` added with architecture reference docs and examples — untracked, not committed

KNOWN ISSUES / BUGS

- FMP API `search-name` endpoint searches company names, not brand names. Subsidiary brands require manual mapping.
- Google Trends rate limiting from Google is aggressive; exponential backoff (5s base, 120s max) mitigates but does not eliminate 429s
- Default password in docker-compose (`eva_password_change_me`) should be rotated for production
- `eva_confidence_v1.py` uses direct `psycopg2.connect()` instead of `eva_common.db.get_connection()` — inconsistent with codebase convention
- `worker.py` has `print()` statements mixed with `logger` calls — should be unified to structlog per CLAUDE.md
- `worker.py` has DEBUG print statements in notification polling section (lines 401-403) that should be removed
- Paper trading scripts use separate `DB_CONFIG` dict with `DB_*` env vars instead of `eva_common.config` — inconsistent with centralized config pattern
- Metabase hardcodes `eva_password_change_me` in docker-compose environment (line 72)

CURRENT FOCAL PROBLEM

Committing and validating Google Trends rate limit hardening. The changes (google_trends.py exponential backoff, eva_confidence_v1.py non-blocking validation, docker-compose port exposure, paper trading script DB host fix) are complete but uncommitted. These changes must be committed, the worker rebuilt, and confidence scoring validated against live data to confirm non-blocking behavior under actual Google rate limiting conditions. This unblocks the full scoring pipeline from being coupled to Google's rate limit behavior and enables reliable paper trade validation during Phase 0.

COLLABORATION WORKFLOW

**Claude Web (architect/planner):**
- Read this snapshot at the start of EVERY session (unless Josh says "skip context")
- Ask 0-2 clarifying questions max, then dive in
- Update "CURRENT FOCAL PROBLEM" when priorities shift
- Generate structured prompts for Claude Code using format below

**Claude Code (executor):**
- Receives structured prompts from Claude Web via Josh
- Executes against codebase with full file access
- Updates "RECENT CHANGES" section after commits

**Josh (orchestrator):**
- Updates snapshot after major architectural changes
- Adds new entries to NEXT STEPS when priorities change
- Commits snapshot changes alongside code

**Prompt Format for Claude Code:**
```
## Task: [One-line goal]

**Context:** [Why we're doing this, what's broken/needed]

**Approach:**
1. Step-by-step plan
2. Files to modify/create
3. Validation steps

**Constraints:**
- Don't touch X
- Watch out for Y
- Must use Z pattern (e.g., eva_common.db.get_connection)

**Success Criteria:**
- How to verify it worked (commands, tests, expected output)

**Files Involved:**
- path/to/file1.py
- path/to/file2.sql
```

VALIDATION PROCEDURES

**After code changes:**
1. Rebuild affected service: `docker compose build eva-worker`
2. Restart: `docker compose up -d eva-worker`
3. Check logs: `docker compose logs eva-worker --tail=100 --follow`
4. Validate behavior: check for expected log output in processing loop

**After schema changes:**
1. Apply migration: `docker exec eva_db psql -U eva -d eva_finance -f /docker-entrypoint-initdb.d/migrations/XXX.sql`
2. Verify table exists: `docker exec eva_db psql -U eva -d eva_finance -c "\dt"`
3. Check view definitions: `docker exec eva_db psql -U eva -d eva_finance -c "\dv"`

**Common validations:**
- DB connection: `docker exec eva_worker python -c "from eva_common.db import get_connection; print('OK')"`
- Config loading: `docker exec eva_worker python -c "from eva_common.config import db_settings, app_settings; print(db_settings.connection_url[:20], app_settings.eva_model)"`
- Worker health: `docker compose logs eva-worker --tail=20`
- API health: `curl -s http://localhost:9080/health`
- Confidence scoring: `docker exec eva_worker python /app/eva_confidence_v1.py`
- Google Trends test: `docker exec eva_worker python -m eva_worker.google_trends Nike`
- Brand mapping: `docker exec eva_worker python /app/brand_research.py --list-unmapped`
- Paper trades: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT ticker, entry_price, current_price, status FROM paper_trades ORDER BY created_at DESC LIMIT 10;"`

**Rollback on failure:**
- If uncommitted: `git checkout -- <file>`
- If service wedged: `docker compose down && docker compose up -d`
- Check last known-good commit: `git log --oneline -5`
- Full reset: `git reset --hard HEAD && docker compose build && docker compose up -d`

DEBUGGING QUICK REFERENCE

**Symptom: Worker stopped processing**
- Check logs: `docker compose logs eva-worker --tail=50`
- Look for uncaught exceptions in main loop
- Verify DB connection: `docker exec eva_worker python -c "from eva_common.db import get_connection; print('OK')"`
- Check container status: `docker compose ps`

**Symptom: No new raw_messages appearing**
- Check ingest logs: `docker compose logs eva-ingest-reddit --tail=50`
- Verify API health: `curl -s http://localhost:9080/health`
- Check recent messages: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT source, COUNT(*) FROM raw_messages WHERE created_at > NOW() - INTERVAL '1 hour' GROUP BY source;"`

**Symptom: No signals generating**
- Check processed messages: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM processed_messages WHERE created_at > NOW() - INTERVAL '1 hour';"`
- Check trigger views: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT * FROM v_eva_candidate_brand_signals_v1 LIMIT 10;"`
- Run confidence scoring manually: `docker exec eva_worker python /app/eva_confidence_v1.py`
- Check signal events: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT event_type, COUNT(*) FROM signal_events WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY event_type;"`

**Symptom: Google Trends returning all pending**
- Check trends metrics: `docker compose logs eva-worker --tail=100 | grep TRENDS-METRICS`
- Test directly: `docker exec eva_worker python -m eva_worker.google_trends Nike`
- Verify pytrends installed: `docker exec eva_worker pip show pytrends`
- Check rate limit env vars: `docker exec eva_worker env | grep GOOGLE_TRENDS`

**Symptom: Brand mapping not resolving tickers**
- Check FMP API key: `docker exec eva_worker env | grep FMP_API_KEY`
- List unmapped: `docker exec eva_worker python /app/brand_research.py --list-unmapped`
- Check mapping table: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT brand_name, ticker, source FROM brand_ticker_mapping ORDER BY created_at DESC LIMIT 20;"`

**Symptom: Notifications not sending**
- Check ntfy container: `docker compose logs ntfy --tail=20`
- Check notification poll logs: `docker compose logs eva-worker --tail=50 | grep notification`
- Test ntfy directly: `curl -d "test" http://localhost:8085/eva-signals`

**Symptom: Paper trades not updating prices**
- Run price updater manually: `python scripts/paper_trading/update_paper_prices.py` (from host with DB_HOST=localhost)
- Check open positions: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT ticker, current_price, updated_at FROM paper_trades WHERE status='open';"`
- Check yfinance: `python -c "import yfinance as yf; print(yf.Ticker('AAPL').history(period='1d'))"`

**Symptom: Database connection pool exhausted**
- Check pool settings: `docker exec eva_worker python -c "from eva_common.config import db_settings; print(f'min={db_settings.db_pool_min}, max={db_settings.db_pool_max}')"`
- Check active connections: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT count(*) FROM pg_stat_activity WHERE datname='eva_finance';"`
- Restart worker: `docker compose restart eva-worker`

OPERATIONAL BASELINES

**Message volume (as of 2026-01-29):**
- Reddit ingestion (8 consumer subreddits): ~200 posts per fetch cycle (25 per sub × 8 subs every 15 min)
- AI infrastructure worker (3 subreddits): ~75 posts per cycle
- Total: ~1,000-2,000 raw messages/day (varies with Reddit activity)

**Processing speed:**
- Brain extraction (LLM): 1-3 seconds per message (OpenAI API latency)
- Brain extraction (fallback): <10ms per message
- Confidence scoring: 2-10 seconds for full run (depends on candidate count)
- Google Trends validation: 5-15 seconds per brand (when not rate limited), 120s+ when backoff kicks in
- Batch processing: 20 messages per cycle, 10s sleep between cycles

**Rate limits (observed behavior):**
- Google Trends: ~20-30 requests/hour before 429s (varies, unpredictable)
- FMP API: ~250 requests/day free tier (500ms enforced delay between calls)
- OpenAI: Not observed as a bottleneck at current volume
- Reddit public JSON: No auth required, ~60 requests/minute practical limit

**Signal output:**
- ~5-15 candidate brand signals/day in current Phase 0 volume
- ~1-5 WATCHLIST_WARM events/day
- ~0-2 RECOMMENDATION_ELIGIBLE events/week

RECENT CHANGES

**Session: January 30, 2026 (uncommitted)**
- Generated updated EVA_CONTEXT_SNAPSHOT.md from full codebase review
- Added `skills/eva-finance/` directory with architecture reference docs and examples (untracked)

**Session: January 29, 2026 (uncommitted)**
- Hardened `google_trends.py`: added `_fetch_with_retry()` with exponential backoff (5s base, 120s max, 3 retries), `_is_rate_limit_error()` detection, `_reset_session()` on rate limits, custom User-Agent header, global rate limiting between all requests, metrics tracking (`log_metrics()`, `get_metrics()`)
- Added `validate_brand_non_blocking()` function that returns `validation_status='pending'` on rate limits
- Updated `eva_confidence_v1.py`: uses `validate_brand_non_blocking()`, only applies confidence boost when `validation_status=='completed'`, logs Google Trends metrics at end of run
- Exposed PostgreSQL port 5432 in `docker-compose.yml` for local tooling
- Fixed paper trading scripts (`check_paper_exits.py`, `update_paper_prices.py`): default DB host changed from hardcoded IP `172.20.0.2` to Docker service name `db`
- Created `EVA_CONTEXT_SNAPSHOT_PROMPT.md` template for generating this snapshot

**Session: January 19, 2026 (committed)**
- `06ce898` feat: automated brand-ticker mapping with FMP API integration
- `0ccde91` Merge branch 'refactor/config-consolidation'
- Created `brand_mapper_service.py`, migration `009_brand_ticker_mapping.sql`
- Integrated brand mapping into worker.py (non-blocking batch processing)

NEXT STEPS (ORDERED)

1. Commit Google Trends hardening changes (google_trends.py, eva_confidence_v1.py, docker-compose.yml, paper trading scripts)
2. Rebuild eva-worker and run confidence scoring against live data to validate non-blocking trends behavior
3. Review Google Trends boost/penalty thresholds against paper trade outcomes
4. Manually map high-signal brands from `v_unmapped_brands` view (Jordan→NKE, Osprey→private, Uniqlo→FRCOY)
5. Migrate `eva_confidence_v1.py` to use `eva_common.db.get_connection()` instead of direct psycopg2
6. Clean up `worker.py`: remove DEBUG print statements, unify print/logger to structlog
7. Migrate paper trading scripts to use `eva_common.config` instead of standalone DB_CONFIG
8. Build Metabase dashboard for Phase 0 validation metrics (win rate, avg return, position count)

INVARIANTS / RULES

- Never hardcode database credentials (use eva_common.config)
- Never use psycopg2 directly in new code (use eva_common.db.get_connection context manager)
- Never block pipeline on external API failures (brand mapping, Google Trends, FMP)
- Never log PII (hash user IDs, no names/emails)
- Financial amounts as integers (cents, not floats)
- UTC timestamps only
- Signal deduplication via database constraints (ON CONFLICT DO NOTHING)
- Paper trading exit rules immutable for Phase 0: 90 days OR +15% OR -10%
- Google Trends validation must not alter confidence when `validation_status='pending'`
- Fallback heuristic extraction must always succeed (never throw)
- All config through Pydantic settings; no `os.getenv()` in new code (except legacy files pending migration)

KEY FILE LOCATIONS

```
eva_common/config.py                              # Pydantic settings (DB, OpenAI, FMP, Google Trends)
eva_common/db.py                                  # Connection pooling (get_connection context manager)
eva_worker/worker.py                              # Main processing loop (brain_extract, emit_trigger_events)
eva_worker/eva_confidence_v1.py                   # Confidence scoring + Google Trends integration
eva_worker/eva_worker/google_trends.py            # Google Trends validator (rate limiting, retry, caching)
eva_worker/eva_worker/brand_mapper_service.py     # FMP API brand-to-ticker mapping
eva_worker/eva_worker/notify.py                   # Notification polling
eva_worker/brand_research.py                      # CLI tool for manual brand mapping
eva_ingest/reddit_posts.py                        # Reddit ingestion module
workers/ai-infrastructure/main.py                 # AI infra worker entry point
scripts/paper_trading/paper_trade_entry.py        # Paper trade creation
scripts/paper_trading/check_paper_exits.py        # Exit condition monitoring
scripts/paper_trading/update_paper_prices.py      # Price update via yfinance
db/init.sql                                       # Core schema (tables, views, indexes, functions)
db/migrations/009_brand_ticker_mapping.sql        # Brand mapping schema
db/migrations/006_google_trends_validation.sql    # Google Trends validation table
db/migrations/005_paper_trading_system.sql        # Paper trading tables and views
docker-compose.yml                                # Service orchestration (7 services)
.env                                              # Secrets (OPENAI_API_KEY, FMP_API_KEY, DB creds)
docs/context/snapshots/EVA_CONTEXT_SNAPSHOT_PROMPT.md  # Prompt template for generating this file
```

QUICK START (RESTORE CONTEXT)

```bash
# Verify system health
docker compose ps
docker exec eva_worker python -c "from eva_common.db import get_connection; print('DB OK')"
docker exec eva_db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM raw_messages;"

# Check uncommitted changes
git diff --stat
git status

# Check recent signal activity
docker exec eva_db psql -U eva -d eva_finance -c "SELECT event_type, COUNT(*) FROM signal_events WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY event_type;"

# Test Google Trends module
docker exec eva_worker python -m eva_worker.google_trends Nike

# Run confidence scoring manually
docker exec eva_worker python /app/eva_confidence_v1.py

# Check brand mapping status
docker exec eva_worker python /app/brand_research.py --list-unmapped

# Check paper trades
docker exec eva_db psql -U eva -d eva_finance -c "SELECT ticker, entry_price, current_price, status FROM paper_trades ORDER BY created_at DESC LIMIT 10;"

# View worker logs
docker compose logs eva-worker --tail=50

# Rebuild and restart worker after changes
docker compose build eva-worker && docker compose up -d eva-worker
```

ENVIRONMENT

- **OS:** Linux 6.8.0-90-generic (Ubuntu)
- **Runtime:** Python 3.12-slim (Docker containers)
- **Database:** PostgreSQL 16 (container: eva_db, port 5432 exposed to host)
- **Services:**
  - eva_db: postgres:16 (port 5432)
  - eva_api: FastAPI (port 9080, internal 8080)
  - eva_worker: background processing (no port)
  - eva_ntfy: ntfy (port 8085)
  - metabase: Metabase (port 3000)
  - eva-ingest-reddit: Reddit fetcher (no port, reuses eva-worker image)
  - eva-ai-infrastructure-worker: AI infra ingestion (no port)
  - n8n: port 5678 (external, connected to eva_net)
- **External APIs:**
  - OpenAI: GPT-4o-mini for extraction
  - FMP: Financial Modeling Prep for ticker lookup (stable API, free tier)
  - Reddit: Public JSON API (no auth required)
  - Google Trends: via pytrends 4.9.2 (rate limited, exponential backoff)
  - yfinance: Stock price data for paper trading
- **Docker network:** eva_net (bridge)

STATUS

System operational. Google Trends rate limit hardening and paper trading script fixes complete but uncommitted. Non-blocking validation prevents pipeline stalls on 429s. Ready to commit, rebuild, and validate against live scoring runs.

LAST UPDATED

2026-01-30
