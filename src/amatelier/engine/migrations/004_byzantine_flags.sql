-- S0: Byzantine Variance Detection — flag columns on scores table
ALTER TABLE scores ADD COLUMN is_flagged BOOLEAN DEFAULT 0;
ALTER TABLE scores ADD COLUMN flagged_since_round INTEGER;
