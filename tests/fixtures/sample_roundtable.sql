-- Seed data for test_db_integration.py
-- Mimics a short real roundtable: briefing -> round 1 (speak + rebuttal) ->
-- round 2 (speak) -> close. Includes a real Judge GATE so GATE-detection tests
-- have something to find.
--
-- Schema is whatever the real migrations produce. This file does NOT create
-- tables; it only INSERTs. Tables must exist first (ensure_user_data applies
-- migrations before the test calls .executescript on this file).
--
-- Timestamps are relative floats starting at a fixed base; deterministic so
-- SVG output is byte-stable across runs.

INSERT INTO roundtables (id, topic, status, participants, created_at, closed_at)
VALUES ('rt-fixture-001', 'Test: does atelier work end-to-end', 'closed',
        'elena,marcus,clare,simon,judge', 1700000000.0, 1700000900.0);

-- Round 1: briefing + phase markers + worker messages + judge GATE + rebuttal
INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES
  ('rt-fixture-001', 'runner', 'BRIEFING:\n\n# Test Briefing\n\nObjective: validate the end-to-end pipeline.', 1700000001.0),
  ('rt-fixture-001', 'runner', 'ROUND 1: begin\nBUDGET STATUS: elena=1, marcus=1, clare=1, simon=1', 1700000002.0),
  ('rt-fixture-001', 'runner', '--- SPEAK PHASE (Round 1) ---', 1700000003.0),
  ('rt-fixture-001', 'runner', 'YOUR TURN: clare -> SPEAK (Round 1, speaker 1/4)', 1700000004.0),
  ('rt-fixture-001', 'clare', 'Structural take: the three options map to a decision tree with three gates.', 1700000010.0),
  ('rt-fixture-001', 'runner', 'YOUR TURN: elena -> SPEAK (Round 1, speaker 2/4)', 1700000011.0),
  ('rt-fixture-001', 'elena', 'Synthesis: Clare''s gate ordering is right but the first gate needs sharpening.', 1700000020.0),
  ('rt-fixture-001', 'runner', 'YOUR TURN: simon -> SPEAK (Round 1, speaker 3/4)', 1700000021.0),
  ('rt-fixture-001', 'simon', 'Triage: focus on the operational constraints before abstract tradeoffs.', 1700000030.0),
  ('rt-fixture-001', 'runner', 'YOUR TURN: marcus -> SPEAK (Round 1, speaker 4/4)', 1700000031.0),
  ('rt-fixture-001', 'marcus', 'Challenge: the consensus is skipping over a cost threshold that flips the answer at scale.', 1700000040.0),
  ('rt-fixture-001', 'judge', 'GATE: marcus - explicit challenge to the emerging consensus, introduces a quantifiable flip point. +3 sparks.', 1700000045.0),
  ('rt-fixture-001', 'runner', '--- REBUTTAL PHASE (Round 1) ---', 1700000050.0),
  ('rt-fixture-001', 'elena', 'Rebuttal: marcus''s flip point is real but applies above a volume threshold most targets never reach.', 1700000060.0),
  ('rt-fixture-001', 'marcus', 'Counter: the target is pre-Series B, not pre-seed. The threshold is within their trajectory.', 1700000070.0);

-- Round 2: speak + close
INSERT INTO messages (roundtable_id, agent_name, message, timestamp) VALUES
  ('rt-fixture-001', 'runner', 'ROUND 2: begin', 1700000080.0),
  ('rt-fixture-001', 'runner', '--- SPEAK PHASE (Round 2) ---', 1700000081.0),
  ('rt-fixture-001', 'clare', 'Converged structure: three gates, fourth is a function of volume trajectory.', 1700000090.0),
  ('rt-fixture-001', 'elena', 'Final synthesis: the answer is hybrid, with the flip point tied to specific volume metrics.', 1700000100.0),
  ('rt-fixture-001', 'simon', 'Ordering confirmed. Decision tree stands.', 1700000110.0),
  ('rt-fixture-001', 'marcus', 'Accept synthesis. The quantification is the load-bearing contribution.', 1700000120.0),
  ('rt-fixture-001', 'judge', 'Round 2 converged. Closing for scoring.', 1700000130.0),
  ('rt-fixture-001', 'runner', 'CLOSE: roundtable sealed for scoring', 1700000140.0);

-- Scores (matches scorer schema)
INSERT INTO scores (roundtable_id, agent_name, novelty, accuracy, impact, challenge, total, reasoning, grand_insight, scored_by, scored_at, is_flagged)
VALUES
  ('rt-fixture-001', 'elena',  2, 2, 2, 1, 7, 'Strong synthesis role', NULL, 'judge-sonnet', 1700000200.0, 0),
  ('rt-fixture-001', 'marcus', 2, 2, 3, 3, 10, 'Load-bearing quantification challenge', NULL, 'judge-sonnet', 1700000200.0, 0),
  ('rt-fixture-001', 'clare',  2, 2, 2, 1, 7, 'Clean structural decomposition', NULL, 'judge-sonnet', 1700000200.0, 0),
  ('rt-fixture-001', 'simon',  1, 2, 1, 1, 5, 'Solid triage; limited novel contribution', NULL, 'judge-sonnet', 1700000200.0, 0);

-- Spark ledger
INSERT INTO spark_ledger (agent_name, amount, reason, category, roundtable_id, created_at) VALUES
  ('elena',  -8, 'RT entry fee (sonnet)', 'entry_fee', 'rt-fixture-001', 1700000002.0),
  ('marcus', -8, 'RT entry fee (sonnet)', 'entry_fee', 'rt-fixture-001', 1700000002.0),
  ('clare',  -5, 'RT entry fee (haiku)',  'entry_fee', 'rt-fixture-001', 1700000002.0),
  ('simon',  -5, 'RT entry fee (haiku)',  'entry_fee', 'rt-fixture-001', 1700000002.0),
  ('marcus',  3, 'GATE bonus',            'gate_bonus', 'rt-fixture-001', 1700000045.0),
  ('elena',   7, 'RT score total',        'rt_earning', 'rt-fixture-001', 1700000200.0),
  ('marcus', 10, 'RT score total',        'rt_earning', 'rt-fixture-001', 1700000200.0),
  ('clare',   7, 'RT score total',        'rt_earning', 'rt-fixture-001', 1700000200.0),
  ('simon',   5, 'RT score total',        'rt_earning', 'rt-fixture-001', 1700000200.0);
