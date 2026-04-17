-- 002_scores_table.sql
-- Per-agent scoring records from Judge evaluations.
-- Replaces the flat score entries in metrics.json with queryable history.

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    roundtable_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    novelty INTEGER NOT NULL DEFAULT 0,
    accuracy INTEGER NOT NULL DEFAULT 0,
    impact INTEGER NOT NULL DEFAULT 0,
    challenge INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    reasoning TEXT,
    grand_insight TEXT,
    scored_by TEXT NOT NULL DEFAULT 'judge-sonnet',
    scored_at REAL NOT NULL,
    FOREIGN KEY (roundtable_id) REFERENCES roundtables(id)
);

CREATE INDEX IF NOT EXISTS idx_scores_rt ON scores(roundtable_id);
CREATE INDEX IF NOT EXISTS idx_scores_agent ON scores(agent_name);