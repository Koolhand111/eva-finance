-- Migration: 008_pivot_ai_infrastructure_subreddits.sql
-- Description: Pivot subreddit list based on 19-hour baseline analysis
-- Date: 2026-01-17
-- Rationale: datacenter (career-focused) and MachineLearning (research-focused)
--            yielded zero company mentions in 451 posts. Adding deployment-focused communities.

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
