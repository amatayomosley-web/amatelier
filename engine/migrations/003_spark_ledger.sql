-- 003_spark_ledger.sql
-- Immutable ledger of all spark transactions: earnings, fees, penalties, purchases.
-- Single source of truth for spark balance (sum of amount WHERE agent_name = X).

CREATE TABLE IF NOT EXISTS spark_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'scoring',
    roundtable_id TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spark_agent ON spark_ledger(agent_name);
CREATE INDEX IF NOT EXISTS idx_spark_rt ON spark_ledger(roundtable_id);