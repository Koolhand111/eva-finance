-- Migration: 007_add_ai_infrastructure_raw_tables.sql
-- Description: Add isolated database tables for AI infrastructure raw post ingestion
-- Date: 2026-01-16
-- Safety: Creates new tables only - does NOT modify existing tables

-- Raw posts storage (no signal extraction yet)
CREATE TABLE ai_infrastructure_raw_posts (
  id SERIAL PRIMARY KEY,
  post_id VARCHAR UNIQUE NOT NULL,
  subreddit VARCHAR NOT NULL,
  title TEXT,
  body TEXT,
  author VARCHAR,
  score INT,
  num_comments INT,
  created_utc BIGINT,
  url TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Subreddit configuration
CREATE TABLE ai_infrastructure_subreddits (
  subreddit_name VARCHAR PRIMARY KEY,
  active BOOLEAN DEFAULT true,
  added_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_ai_raw_posts_subreddit ON ai_infrastructure_raw_posts(subreddit);
CREATE INDEX idx_ai_raw_posts_created ON ai_infrastructure_raw_posts(created_at);
CREATE INDEX idx_ai_raw_posts_post_id ON ai_infrastructure_raw_posts(post_id);

-- Initial subreddit list (Phase 1: Core 5)
INSERT INTO ai_infrastructure_subreddits (subreddit_name, active) VALUES
  ('datacenter', true),
  ('sysadmin', true),
  ('homelab', true),
  ('LocalLLaMA', true),
  ('MachineLearning', true);
