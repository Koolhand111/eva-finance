# EVA-Finance — Project Map

## Purpose
Detect behavioral trend signals early using conversational data.

## Core Concepts
- Tags represent behaviors, not products
- Brand flow models switching pressure
- Confidence is multi-factor, not binary

## Key Files
- eva_worker/worker.py — ingestion + extraction
- eva_worker/scoring.py — signal scoring logic
- db/views/*.sql — signal derivations

## Design Decisions
- LLM first, heuristics second
- Prefer false negatives over false positives
- Persistence > spike magnitude
