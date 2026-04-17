-- 001_initial.sql
-- Base roundtable schema: tables, indexes, core structure.
-- Safe to run against an existing DB (IF NOT EXISTS throughout).

CREATE TABLE IF NOT EXISTS roundtables (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    participants TEXT,
    created_at REAL NOT NULL,
    closed_at REAL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    roundtable_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp REAL NOT NULL,
    FOREIGN KEY (roundtable_id) REFERENCES roundtables(id)
);

CREATE TABLE IF NOT EXISTS read_cursors (
    agent_name TEXT NOT NULL,
    roundtable_id TEXT NOT NULL,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_name, roundtable_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_rt ON messages(roundtable_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_name);
CREATE INDEX IF NOT EXISTS idx_messages_rt_id ON messages(roundtable_id, id);