# EVA-Finance Phase 0 Validation Roadmap

**Timeline:** 12 weeks (January 2026 - March 2026)  
**Effort:** ~9 hours/week  
**Goal:** Validate investment thesis through forward-looking paper trading

---

## Overview

Phase 0 validates whether social behavioral trends predict stock performance using paper trading with real market data. This roadmap runs in parallel with automated paper trading to prepare Phase 1 infrastructure.

**Context:**
- Reddit API access denied (no historical data available)
- Paper trading system deployed and operational
- Validation through forward-looking data only
- 12-week timeline to accumulate sufficient closed trades

---

## Success Criteria (Week 12 Decision Point)

**GO to Phase 1 if:**
- ✅ Win rate ≥ 50%
- ✅ Average return ≥ 5%
- ✅ ≥10 closed paper trades
- ✅ Repeatable, automated process
- ✅ Understanding of why strategy works

**CAUTIOUS GO if:**
- ⚠️ 2 of 3 criteria met
- ⚠️ Promising but needs more samples

**NO-GO if:**
- ❌ Win rate < 40% after 12 weeks
- ❌ Consistent underperformance
- ❌ Unable to generate tradeable signals

---

## Weeks 1-2: Foundation & Quick Wins

### Week 1: Monitoring & Visibility
**Goal:** Make paper trading performance visible

**Tasks:**
- [ ] Build Metabase dashboard (4 hours)
  - Win rate gauge
  - Open positions table (v_open_positions)
  - Closed positions history (v_closed_positions)
  - Validation status indicator (v_paper_trading_performance)
  - Real-time metrics display

- [ ] Set up Google Trends integration (3 hours)
  - Install pytrends package
  - Create brand search interest tracking script
  - Cross-validate social signals with search trends
  - Reference: `/mnt/skills/user/social-signal-trading/references/validation.md` lines 316-344

- [ ] Expand brand-ticker mapping (2 hours)
  - Research publicly-traded consumer brands
  - Add to BRAND_TO_TICKER dict in paper_trade_entry.py
  - Focus: athletic, outdoor, fashion brands
  - Materiality research: brand revenue % of parent company

**Deliverables:**
- Metabase dashboard with real-time validation metrics
- Google Trends cross-validation script
- Expanded brand coverage (20+ → 30+ brands)

---

### Week 2: Data Quality & Signal Refinement
**Goal:** Improve signal quality before Phase 1

**Tasks:**
- [ ] Audit current signals (3 hours)
  - Query all RECOMMENDATION_ELIGIBLE signals
  - Analyze false positives (test brands, weak signals)
  - Review suppression effectiveness
  - Document signal quality issues

- [ ] Tune confidence thresholds (4 hours)
  - Review gate logic: spread, velocity, sentiment, cross-community
  - Test threshold adjustments
  - Goal: Reduce false positives while maintaining sensitivity
  - Document recommended tuning parameters
  - Reference: `/mnt/skills/user/social-signal-trading/references/signal-scoring.md`

- [ ] LLM extraction quality check (2 hours)
  - Sample 50 processed messages
  - Verify brand extraction accuracy
  - Check behavioral tag quality
  - Identify extraction improvements

**Deliverables:**
- Signal quality analysis document
- Recommended confidence threshold adjustments
- LLM extraction quality report

---

## Weeks 3-6: Phase 1 Preparation (Critical Gaps)

### Week 3: E-commerce Data Pipeline Design
**Goal:** Design system to track product availability and sales velocity

**Tasks:**
- [ ] Research e-commerce data sources (3 hours)
  - Amazon Product Advertising API (official)
  - Rainforest API (paid but structured)
  - Shopify public data
  - Compare costs, rate limits, data quality
  - Reference: `/mnt/skills/user/social-signal-trading/references/data-sources.md` lines 256-283

- [ ] Design schema for e-commerce data (2 hours)
  ```sql
  CREATE TABLE ecommerce_data (
      id SERIAL PRIMARY KEY,
      brand TEXT,
      product_id TEXT,
      availability BOOLEAN,
      price NUMERIC,
      review_count INTEGER,
      review_velocity NUMERIC,  -- Reviews per day
      timestamp TIMESTAMPTZ DEFAULT NOW(),
      INDEX idx_brand_timestamp (brand, timestamp)
  );
  ```

- [ ] Build prototype scraper/API client (4 hours)
  - Proof-of-concept for one source
  - Test data quality and availability
  - Estimate costs and rate limits
  - Document integration approach

**Deliverables:**
- E-commerce integration design document
- Working prototype for chosen source
- Cost/benefit analysis

---

### Week 4: Brand Materiality Framework
**Goal:** Distinguish material brands from noise

**Tasks:**
- [ ] Build brand materiality scoring (4 hours)
  - Revenue % of parent company
  - Growth lever potential (is brand significant?)
  - Market cap impact threshold
  - Examples:
    - Hoka = 35% of DECK revenue → HIGH materiality
    - North Face = <20% of VFC → LOW materiality
  - Scoring algorithm: 0-1 scale

- [ ] Create materiality database (3 hours)
  ```sql
  CREATE TABLE brand_materiality (
      brand TEXT PRIMARY KEY,
      ticker TEXT,
      parent_company TEXT,
      revenue_pct NUMERIC,       -- % of parent revenue
      growth_lever BOOLEAN,      -- Strategic importance
      materiality_score NUMERIC, -- 0-1 composite score
      notes TEXT,
      updated_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```

- [ ] Integrate into confidence scoring (2 hours)
  - Add materiality gate to scoring logic
  - Weight high-materiality brands higher
  - Suppress or flag low-materiality signals
  - Test impact on signal volume

**Deliverables:**
- Brand materiality database (30+ brands scored)
- Materiality-weighted confidence scoring
- Documentation of materiality impact

**Milestone:** Google Trends + Materiality framework operational

---

### Week 5: News Source Integration
**Goal:** Add professional media validation layer

**Tasks:**
- [ ] Set up news RSS feeds (3 hours)
  - Google News RSS for brand queries
  - NewsAPI.org (free tier: 100 requests/day)
  - Industry publications:
    - Footwear News
    - WWD (Women's Wear Daily)
    - Business of Fashion
  - Reference: `/mnt/skills/user/social-signal-trading/references/data-sources.md` lines 298-326

- [ ] Build news ingestion pipeline (4 hours)
  - n8n workflow for RSS polling (hourly)
  - Store in news_mentions table
  - LLM extraction for sentiment/relevance
  - Link to brands and signals

- [ ] Cross-source validation logic (2 hours)
  - Signal strength: Reddit + News = HIGH confidence
  - Timing analysis: Does news lead or lag social?
  - Weight news signals higher (professional validation)
  - Test multi-source fusion algorithm

**Deliverables:**
- News ingestion pipeline operational
- Multi-source signal fusion system (Reddit + News)
- Cross-source timing analysis

---

### Week 6: Market Data Integration
**Goal:** Connect signals to actual market performance

**Tasks:**
- [ ] Historical price data pipeline (3 hours)
  - yfinance bulk download for all tickers
  - Store in stock_prices table
  - Daily OHLCV data
  - Calculate: SMA(20), SMA(50), volatility, volume

- [ ] Signal-to-performance correlation (4 hours)
  - For each historical signal, measure subsequent returns
  - Calculate correlation: signal confidence vs returns
  - Identify optimal holding periods (30d, 60d, 90d)
  - Validate paper trading exit rules (90d, +15%, -10%)
  - Statistical significance testing

- [ ] Market context scoring (2 hours)
  - Add market regime detection (bull/bear/volatile)
  - Adjust confidence based on market conditions
  - Example: Higher confidence bar during bear markets
  - VIX integration for volatility context

**Deliverables:**
- Historical price database (all tracked tickers)
- Signal effectiveness correlation analysis
- Market regime-aware confidence adjustments

**Milestone:** Multi-source fusion operational (Reddit + News + Trends + Market)

---

## Weeks 7-10: Infrastructure Expansion

### Week 7-8: Alternative Social Sources
**Goal:** Reduce Reddit dependency, diversify signal sources

**Tasks:**
- [ ] Twitter/X API exploration (4 hours)
  - Evaluate cost vs benefit:
    - Free tier: 1,500 posts/month (too limited)
    - Basic tier: $100/month for 10k posts
  - Build prototype scraper if budget allows
  - Compare Twitter signal quality to Reddit
  - Decision: Worth $100/month investment?
  - Reference: `/mnt/skills/user/social-signal-trading/references/data-sources.md` lines 156-215

- [ ] Discord bot (optional) (3 hours)
  - Identify relevant communities:
    - Sneakerhead servers
    - Fashion communities
    - Athletic gear enthusiasts
  - Build read-only bot
  - Test signal quality vs Reddit
  - Ethical consideration: Community permission required

- [ ] YouTube monitoring (optional) (2 hours)
  - Track major reviewer channels
  - Product review velocity detection
  - Transcript extraction via YouTube API
  - Estimate signal value vs implementation cost

**Deliverables:**
- Source evaluation report (cost/benefit analysis)
- Decision on which sources to add in Phase 2
- Prototype integrations for approved sources

---

### Week 9: System Hardening
**Goal:** Production-ready infrastructure

**Tasks:**
- [ ] Error handling & monitoring (4 hours)
  - Comprehensive structured logging (structlog)
  - Health check endpoints for all services
  - Dead letter queue for failed messages
  - Retry logic with exponential backoff
  - Alert thresholds and notification setup
  - Reference: `/mnt/skills/user/social-signal-trading/references/architecture.md` lines 262-311

- [ ] Backup & disaster recovery (3 hours)
  - Automated PostgreSQL backups (daily + weekly)
  - Schema version control (migrations directory)
  - Database migration strategy (alembic or similar)
  - Test restore procedure (document recovery time)
  - Backup verification automation

- [ ] Performance optimization (2 hours)
  - Add database indexes where needed
  - Identify and optimize slow queries (EXPLAIN ANALYZE)
  - Worker scaling strategy (horizontal scaling plan)
  - Connection pooling configuration
  - Cache strategy for frequently accessed data

**Deliverables:**
- Hardened production system with monitoring
- Disaster recovery runbook
- Performance baseline and optimization plan

**Milestone:** Production-ready infrastructure

---

### Week 10: Documentation & Knowledge Base
**Goal:** Create operational playbooks

**Tasks:**
- [ ] System architecture documentation (3 hours)
  - Update EVA_CONTEXT_SNAPSHOT.md
  - Component interaction diagrams (mermaid)
  - Data flow documentation
  - Decision logs (ADRs - Architecture Decision Records)
  - API documentation (OpenAPI/Swagger)

- [ ] Operational runbooks (4 hours)
  - Troubleshooting guide (common issues + solutions)
  - Database maintenance procedures
  - Deployment checklist
  - Incident response playbook
  - On-call procedures (if applicable)
  - Monitoring and alerting guide

- [ ] Phase 1 roadmap refinement (2 hours)
  - Update based on Phase 0 learnings
  - Reprioritize features
  - Budget and resource planning
  - Timeline estimation for Phase 1
  - Risk assessment

**Deliverables:**
- Complete technical documentation package
- Operational runbooks for system management
- Refined Phase 1 implementation plan

---

## Weeks 11-12: Validation Review & Decision

### Week 11: Validation Analysis
**Goal:** Evaluate Phase 0 results comprehensively

**Tasks:**
- [ ] Paper trading performance review (3 hours)
  ```sql
  -- Performance metrics
  SELECT 
      total_closed_trades,
      win_rate_pct,
      avg_return_pct,
      avg_winner_return_pct,
      avg_loser_return_pct,
      best_return_pct,
      worst_return_pct,
      avg_days_held
  FROM v_paper_trading_performance;
  
  -- Breakdown by brand
  SELECT 
      brand,
      COUNT(*) as trades,
      AVG(return_pct) as avg_return,
      SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as win_rate
  FROM v_closed_positions
  GROUP BY brand
  ORDER BY trades DESC;
  
  -- Breakdown by confidence band
  SELECT 
      CASE 
          WHEN signal_confidence >= 0.8 THEN 'HIGH'
          WHEN signal_confidence >= 0.6 THEN 'MEDIUM'
          ELSE 'LOW'
      END as confidence_band,
      COUNT(*) as trades,
      AVG(return_pct) as avg_return
  FROM v_closed_positions
  GROUP BY confidence_band;
  ```
  - Analyze all closed positions
  - Win rate breakdown: brand, tag, confidence level
  - Time to profit analysis
  - Exit reason analysis (90d vs profit target vs stop loss)

- [ ] Signal quality analysis (4 hours)
  - False positive rate calculation
  - Signal volume per week (trend over 12 weeks)
  - Confidence score distribution
  - Cross-source validation effectiveness
  - Suppression effectiveness review

- [ ] Market correlation study (2 hours)
  - Do social trends predict returns? (statistical tests)
  - Optimal signal-to-entry lag
  - Which brands/categories work best?
  - Market regime impact on performance
  - Benchmark comparison (SPY, sector indices)

**Deliverables:**
- Comprehensive validation report (15-20 pages)
- Statistical analysis of signal effectiveness
- Recommendation for Phase 1 prioritization

---

### Week 12: GO/NO-GO Decision
**Goal:** Decide on Phase 1 investment

**Tasks:**
- [ ] Validation criteria check (2 hours)
  - ✅ Win rate ≥50%?
  - ✅ Avg return ≥5%?
  - ✅ ≥10 closed trades?
  - ✅ Repeatable automated process?
  - ✅ Understanding of why it works?
  - ✅ Confidence in risk management?
  - Document gaps or concerns

- [ ] Strategic assessment (3 hours)
  - **GO Decision Path:**
    - All 3 validation criteria met
    - Clear alpha generation mechanism
    - Confidence in thesis
    - → Proceed to Phase 1 (4-6 weeks, ~$2-5k investment)
  
  - **CAUTIOUS GO Path:**
    - 2 of 3 criteria met
    - Promising but needs refinement
    - → Iterate on signal scoring, test 4 more weeks
  
  - **NO-GO Path:**
    - <2 criteria met
    - No clear alpha generation
    - → Pivot: Different data sources? Different thesis?
    - → Document learnings before abandoning

- [ ] Phase 1 implementation plan (if GO) (4 hours)
  - Prioritize Phase 1 features:
    1. Multi-source fusion (Twitter? Discord?)
    2. E-commerce velocity tracking
    3. News sentiment analysis
    4. Market regime detection
  - Budget allocation (~$100-200/month operational)
  - Timeline: 4-6 weeks implementation
  - Success metrics for Phase 1
  - Risk mitigation plan

**Deliverables:**
- GO/NO-GO decision document with rationale
- Phase 1 implementation plan (if GO)
- Lessons learned document (regardless of outcome)
- Updated EVA-Finance strategy document

**Milestone:** Thesis validation complete, Phase 1 decision made

---

## Key Milestones Summary

| Week | Milestone | Success Indicator |
|------|-----------|-------------------|
| 1 | Dashboard operational | Real-time validation metrics visible |
| 4 | Trends + Materiality | Google Trends integrated, materiality scoring live |
| 6 | Multi-source fusion | Reddit + News + Trends correlation working |
| 9 | Production-ready | Monitoring, backups, runbooks complete |
| 12 | GO/NO-GO | Clear decision on Phase 1 investment |

---

## Validation Metrics to Track

**Weekly checks:**
```sql
-- Quick validation status
SELECT 
    total_closed_trades as closed,
    open_positions as open,
    win_rate_pct as win_rate,
    avg_return_pct as avg_return,
    CASE
        WHEN total_closed_trades >= 10 
         AND win_rate_pct >= 50 
         AND avg_return_pct >= 5 
        THEN '✓ VALIDATION SUCCESS'
        WHEN total_closed_trades < 10 
        THEN '⏳ Need more samples (' || (10 - total_closed_trades) || ' more)'
        ELSE '⊘ Criteria not met'
    END AS status
FROM v_paper_trading_performance;
```

**Track over time:**
- Closed trades count (target: 10+)
- Win rate % (target: ≥50%)
- Average return % (target: ≥5%)
- Signal volume per week
- False positive rate

---

## Risk Mitigation

**What could go wrong:**

1. **Insufficient signal volume**
   - Mitigation: Expand subreddit coverage, add sources earlier
   - Fallback: Extend Phase 0 timeline to 16 weeks

2. **Poor win rate (<40%)**
   - Mitigation: Tune confidence thresholds weekly
   - Fallback: Pivot to different signal types or data sources

3. **Low materiality brands dominating**
   - Mitigation: Implement materiality weighting by Week 4
   - Fallback: Focus only on high-materiality brands (>20% revenue)

4. **Market regime changes**
   - Mitigation: Track performance by market regime
   - Fallback: Adjust strategy for different market conditions

---

## Resources & References

**Skill documentation:**
- Architecture: `/mnt/skills/user/social-signal-trading/references/architecture.md`
- Data sources: `/mnt/skills/user/social-signal-trading/references/data-sources.md`
- Signal scoring: `/mnt/skills/user/social-signal-trading/references/signal-scoring.md`
- Validation: `/mnt/skills/user/social-signal-trading/references/validation.md`

**External tools:**
- Metabase: http://localhost:3000 (or configured port)
- n8n: http://10.10.0.210:5678/
- Paper trading logs: `/home/koolhand/logs/eva/paper_*.log`

**Key queries:**
```sql
-- Performance summary
SELECT * FROM v_paper_trading_performance;

-- Open positions
SELECT * FROM v_open_positions ORDER BY current_return_pct DESC;

-- Recent closes
SELECT * FROM v_closed_positions ORDER BY exit_date DESC LIMIT 10;

-- Brand performance
SELECT 
    brand,
    COUNT(*) as trades,
    AVG(return_pct) as avg_return,
    STDDEV(return_pct) as volatility
FROM v_closed_positions
GROUP BY brand
HAVING COUNT(*) >= 3
ORDER BY avg_return DESC;
```

---

## Notes

**Last updated:** January 9, 2026  
**Phase:** 0 (Validation)  
**Status:** In progress  
**Reddit API:** Denied (no historical data available)  
**Validation method:** Paper trading with live market data  

**Progress tracking:**
- [ ] Week 1
- [ ] Week 2
- [ ] Week 3
- [ ] Week 4
- [ ] Week 5
- [ ] Week 6
- [ ] Week 7-8
- [ ] Week 9
- [ ] Week 10
- [ ] Week 11
- [ ] Week 12
- [ ] GO/NO-GO Decision

---

*This roadmap is a living document. Update as learnings emerge and priorities shift.*
