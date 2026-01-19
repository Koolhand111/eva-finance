# AI Infrastructure Subreddit Pivot

**Date:** 2026-01-17
**Status:** Implemented

## Summary

After 19 hours of baseline data collection (451 posts), we pivoted the AI infrastructure subreddit list to improve signal quality for company/vendor mentions.

## Baseline Analysis Results

| Subreddit | Posts Collected | Company Mentions | Signal Quality |
|-----------|-----------------|------------------|----------------|
| datacenter | ~90 | 0 | Low - career/job focused |
| MachineLearning | ~90 | 0 | Low - research/paper focused |
| sysadmin | ~90 | Some | Medium - operational |
| homelab | ~90 | Some | Medium - hardware discussions |
| LocalLLaMA | ~90 | Some | High - deployment focused |

**Key Finding:** Zero company mentions from datacenter and MachineLearning despite significant post volume.

## Why We're Dropping These Subreddits

### r/datacenter
- **Content type:** Primarily career advice, job postings, certification discussions
- **Signal gap:** Users discuss "working at a datacenter" rather than "deploying infrastructure"
- **Company mentions:** None in 19-hour sample
- **Conclusion:** Not relevant for vendor/infrastructure intelligence

### r/MachineLearning
- **Content type:** Research papers, academic discussions, theoretical ML
- **Signal gap:** Focus on algorithms and models, not deployment infrastructure
- **Company mentions:** None in 19-hour sample (papers cite authors, not vendors)
- **Conclusion:** Wrong audience for infrastructure deployment discussions

## Why We're Adding These Subreddits

### r/networking
- **Expected content:** Network infrastructure, vendor comparisons, deployment experiences
- **Signal potential:** High - professionals discussing Cisco, Arista, Juniper, etc.
- **Relevance:** Core infrastructure layer for AI deployments

### r/selfhosted
- **Expected content:** Self-hosted infrastructure, hardware choices, deployment guides
- **Signal potential:** High - users compare and recommend specific products/vendors
- **Relevance:** Grassroots infrastructure decisions, often precedes enterprise adoption

### r/semiconductors
- **Expected content:** Chip industry news, GPU/accelerator discussions, supply chain
- **Signal potential:** High - NVIDIA, AMD, Intel, custom silicon discussions
- **Relevance:** Hardware layer driving AI infrastructure decisions

## Final Subreddit List

### Active (6 subreddits)
| Subreddit | Rationale |
|-----------|-----------|
| sysadmin | Enterprise operations, vendor discussions |
| homelab | Hardware decisions, product recommendations |
| LocalLLaMA | AI deployment specifics, GPU discussions |
| networking | Network infrastructure, vendor comparisons |
| selfhosted | Infrastructure choices, product reviews |
| semiconductors | Hardware/chip industry, GPU market |

### Deactivated (2 subreddits)
| Subreddit | Reason |
|-----------|--------|
| datacenter | Career-focused, zero vendor signal |
| MachineLearning | Research-focused, zero vendor signal |

## Expected Signal Improvement

- **Before:** 5 subreddits, 2 with zero signal = 40% dead weight
- **After:** 6 subreddits, all deployment/infrastructure focused
- **Expected lift:** 2-3x company mention rate based on subreddit content profiles

## Implementation

Migration applied: `db/migrations/008_pivot_ai_infrastructure_subreddits.sql`

```sql
-- Deactivate poor-signal subreddits
UPDATE ai_infrastructure_subreddits
SET active = false
WHERE subreddit_name IN ('datacenter', 'MachineLearning');

-- Add new high-potential subreddits
INSERT INTO ai_infrastructure_subreddits (subreddit_name, active) VALUES
  ('networking', true),
  ('selfhosted', true),
  ('semiconductors', true)
ON CONFLICT (subreddit_name) DO UPDATE SET active = true;
```

## Monitoring

After restart, verify new subreddits are being fetched:

```bash
docker compose logs -f eva-ai-infrastructure-worker
```

Expected output:
```
Monitoring 6 subreddits: sysadmin, homelab, LocalLLaMA, networking, selfhosted, semiconductors
```

## Next Steps

1. Collect 24-48 hours of data from new subreddit mix
2. Analyze company mention rate improvement
3. Consider adding more specialized subreddits if signal remains low
