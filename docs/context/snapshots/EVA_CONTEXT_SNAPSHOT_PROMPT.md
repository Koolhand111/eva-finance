You are reviewing the EVA-Finance repository.

Your task is to generate an **Engineering Continuation Snapshot** whose sole
purpose is to restore full working context in a fresh ChatGPT conversation.

This is a resume-from-interrupt artifact, not documentation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT RULES (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Do NOT modify or overwrite this prompt file
- Write output ONLY to the following path:
  docs/context/snapshots/EVA_CONTEXT_SNAPSHOT.md
- Overwrite that file completely
- Do NOT write to any other files
- Do NOT include commentary outside the snapshot
- Treat the section headers below as a STRICT CONTRACT

If any required section is missing, renamed, merged, or reordered,
the output is invalid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ASSUMPTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Reader is a senior engineer
- Reader understands Python, Postgres, Docker, async workers, cron
- Precision > verbosity
- Operational truth > narrative
- No philosophy, no vision, no marketing language

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REQUIRED OUTPUT FORMAT
(HEADERS MUST MATCH EXACTLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

=== EVA-Finance Engineering Continuation Snapshot ===

PROJECT PURPOSE
- One short paragraph (max 5 sentences)
- Explicit in-scope
- Explicit out-of-scope

MENTAL MODEL / EXECUTION ASSUMPTIONS
- Bullet list only
- Non-obvious operational constraints
- Expectations that guide correct engineering decisions
- Architecture decisions with rationale (why X over Y when not obvious)
- If this section is missing, the output is invalid

CURRENT ARCHITECTURE
- Ingest sources
- Processing pipeline
- Workers / schedulers
- Persistence layer (key tables only)
- Output artifacts

WHAT IS WORKING (END-TO-END)
- Bullet list of flows that fully complete successfully

WHAT IS PARTIALLY WORKING
- Bullet list
- What exists vs what is missing or manual

KNOWN ISSUES / BUGS
- Bullet list
- Include root-cause hypotheses if known

CURRENT FOCAL PROBLEM
- The single problem actively being solved
- Why it blocks forward progress

COLLABORATION WORKFLOW
- How Claude Web (architect/planner) uses this snapshot
- How Claude Code (executor) receives tasks
- How Josh (orchestrator) maintains this document
- Prompt format specification for Claude Web → Claude Code handoffs
- Include example prompt structure in markdown code block

VALIDATION PROCEDURES
- Commands to run after code changes (grouped by scenario)
- Service restart patterns
- Common health checks (DB connection, config loading, API tests)
- Rollback procedures if something breaks
- All commands must be copy-pasteable

DEBUGGING QUICK REFERENCE
- Symptom → diagnostic command mappings
- Format: "**Symptom:** Description" followed by "- Check X: `command`"
- Common failure patterns and their fixes
- Where to look first when X stops working
- Focus on the 5-10 most common debugging scenarios

OPERATIONAL BASELINES
- Message volume and processing speed benchmarks
- External API rate limits (actual observed behavior, not documented limits)
- Typical signal output rates (per hour/day/week)
- Processing latencies (extraction, scoring, validation)
- Include timestamps or "as of DATE" for all metrics

RECENT CHANGES
- Last 1–2 work sessions only
- Include commits if available
- Include important uncommitted changes

NEXT STEPS (ORDERED)
1.
2.
3.
- Concrete, technical actions only
- No aspirational or vague items

INVARIANTS / RULES
- Things that must NOT be broken
- Design constraints already agreed upon

KEY FILE LOCATIONS
- Only files relevant to current work
- Include relative paths

QUICK START (RESTORE CONTEXT)
- Minimal commands to:
  - Verify system health
  - Run critical manual steps
  - Inspect current state

ENVIRONMENT
- OS
- Runtime versions
- Services
- Ports
- External dependencies

STATUS
- One-line summary of system readiness

LAST UPDATED
- YYYY-MM-DD

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STYLE CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- No prose outside bullet points unless explicitly allowed
- No rewording of section headers
- No additional sections
- No speculation
- No future vision
- Treat this as an engineer-to-engineer handoff under time pressure

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COLLABORATION WORKFLOW SECTION TEMPLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use this exact structure for the COLLABORATION WORKFLOW section:

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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VALIDATION PROCEDURES SECTION TEMPLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Group by scenario, include exact commands:

**After code changes:**
1. Rebuild affected service: `docker compose build [service-name]`
2. Restart: `docker compose up -d [service-name]`
3. Check logs: `docker compose logs [service-name] --tail=100 --follow`
4. Validate behavior: [depends on change]

**Common validations:**
- DB connection: `docker exec eva_worker python -c "from eva_common.db import get_connection; print('OK')"`
- Config loading: `docker exec eva_worker python -c "from eva_common.config import settings; print(settings.DB_HOST)"`
- [Add service-specific tests]

**Rollback on failure:**
- If uncommitted: `git reset --hard HEAD`
- If service wedged: `docker compose down && docker compose up -d`
- Check last known-good commit: `git log --oneline -5`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEBUGGING QUICK REFERENCE SECTION TEMPLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use this format for each common issue:

**Worker stopped processing:**
- Check logs: `docker compose logs eva-worker --tail=50`
- Look for uncaught exceptions in main loop
- Verify DB connection: `docker exec eva_worker python -c "from eva_common.db import get_connection; print('OK')"`

**No signals generating:**
- Check processed messages: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT COUNT(*) FROM processed_messages WHERE created_at > NOW() - INTERVAL '1 hour';"`
- Check trigger views: `docker exec eva_db psql -U eva -d eva_finance -c "SELECT * FROM v_eva_candidate_brand_signals_v1 LIMIT 10;"`
- Run confidence scoring manually: `docker exec eva_worker python /app/eva_confidence_v1.py`

[Add 5-10 most common scenarios]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPERATIONAL BASELINES SECTION TEMPLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Include actual observed metrics with timestamps:

**Message volume (as of YYYY-MM-DD):**
- Reddit ingestion: ~X messages/hour
- AI infra worker: ~Y messages/hour
- Total: ~Z messages/day

**Processing speed:**
- Confidence scoring: X-Y seconds for full run
- Google Trends validation: X-Y seconds per brand (when not rate limited)
- Brain extraction: X seconds per message

**Rate limits (observed behavior):**
- Google Trends: ~X-Y requests/hour before 429s
- FMP API: [observed limit]
- OpenAI: [observed limit]

**Signal output:**
- ~X-Y signals/day in current Phase 0 volume
- ~X-Y RECOMMENDATION_ELIGIBLE events/week