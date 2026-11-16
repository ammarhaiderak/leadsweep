-- Migration 002: LeadSweep Studio Relational Data Model
-- Tracked via PRAGMA user_version = 2

-- 1. Targets for Follower Intelligence
CREATE TABLE IF NOT EXISTS targets (
  id TEXT PRIMARY KEY,
  handle TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('competitor', 'influencer', 'customer', 'prospect')),
  notes TEXT,
  enabled INTEGER DEFAULT 1,
  schedule TEXT,
  caps_override TEXT,
  last_run_at TEXT,
  last_cursor TEXT,
  approx_followers INTEGER,
  created_at TEXT NOT NULL
);

-- 2. Follower Profiles (Enriched X Users)
CREATE TABLE IF NOT EXISTS x_users (
  rest_id TEXT PRIMARY KEY,
  handle TEXT NOT NULL,
  name TEXT,
  bio TEXT,
  location TEXT,
  website TEXT,
  followers_count INTEGER,
  following_count INTEGER,
  tweets_count INTEGER,
  listed_count INTEGER,
  created_at TEXT,
  is_blue_verified INTEGER,
  verified_type TEXT,
  protected INTEGER DEFAULT 0,
  avatar_url TEXT,
  professional_category TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_x_users_handle ON x_users(handle);

-- 3. Follower Edges (Tracking Growth, Churn & Overlap across Targets)
CREATE TABLE IF NOT EXISTS follow_edges (
  target_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  first_seen_run TEXT NOT NULL,
  last_seen_run TEXT NOT NULL,
  active INTEGER DEFAULT 1,
  PRIMARY KEY (target_id, user_id),
  FOREIGN KEY (target_id) REFERENCES targets(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES x_users(rest_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_follow_edges_user ON follow_edges(user_id);

-- 4. Follower Extraction Run Snapshots
CREATE TABLE IF NOT EXISTS follower_runs (
  id TEXT PRIMARY KEY,
  target_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  pulled_count INTEGER DEFAULT 0,
  new_count INTEGER DEFAULT 0,
  lost_count INTEGER DEFAULT 0,
  coverage_percent REAL,
  status TEXT NOT NULL,
  error_code TEXT,
  FOREIGN KEY (target_id) REFERENCES targets(id)
);

-- 5. User Qualification & ICP Scores
CREATE TABLE IF NOT EXISTS user_scores (
  user_id TEXT PRIMARY KEY,
  icp_score INTEGER NOT NULL,
  persona TEXT,
  fit_reason TEXT,
  outreach_angle TEXT,
  scored_by TEXT NOT NULL,
  scored_at TEXT NOT NULL,
  rules_score INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES x_users(rest_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_scores_icp ON user_scores(icp_score DESC);

-- 6. Unified Workflow Triage (For both Tweets and User Profiles)
CREATE TABLE IF NOT EXISTS lead_workflow (
  entity_id TEXT PRIMARY KEY, -- tweet_id or rest_id
  entity_type TEXT NOT NULL CHECK(entity_type IN ('tweet', 'user')),
  status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'reviewing', 'contacted', 'replied', 'won', 'lost', 'ignored')),
  owner TEXT,
  tags TEXT, -- JSON array of strings
  notes TEXT,
  updated_at TEXT NOT NULL
);

-- 7. Feedback & Evaluation Loop
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('tweet', 'user')),
  label TEXT NOT NULL CHECK(label IN ('good', 'bad')),
  reason_code TEXT,
  note TEXT,
  created_at TEXT NOT NULL
);

-- 8. Persistent Background Jobs
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL, -- 'leads_pipeline', 'followers_pull', 'rescore'
  params TEXT, -- JSON string of job input
  status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'paused')),
  progress_percent INTEGER DEFAULT 0,
  current_step TEXT,
  result_summary TEXT, -- JSON stats
  error_code TEXT,
  error_detail TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
