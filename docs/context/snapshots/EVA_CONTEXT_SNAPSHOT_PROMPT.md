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
