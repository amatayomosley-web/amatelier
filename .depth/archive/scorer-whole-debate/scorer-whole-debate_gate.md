TASK: scorer-whole-debate
SCOPE: non-trivial
FILES: src/amatelier/engine/judge_scorer.py, tests/test_judge_transcript.py
REPLACES: `MAX_MSG = 1200` — judge_scorer.py _format_transcript cut each message at 1,200 characters and the whole transcript at 20,000, so later phases of a debate (the floor, where proposals converge) never reached the scorer; judge_score cut the briefing at 3,000 characters and the retry cut the transcript at 15,000; agents were labelled by their real names; debate posted in the research window was scored. Now the whole debate is formatted (ceilings 8,000 per message and 200,000 in total, a cut is logged), agents are scored under random reviewer labels with their names scrubbed from the text and the briefing and mapped back after parsing, the judge's own posts are labelled Moderator, a worker's research-window post counts only when it makes a [[request:]], and the scorer receives the whole briefing (ceiling 60,000, logged)
MIGRATION: none — judge_score keeps its signature and return; _format_transcript and _parse_scores are private (_format_transcript now also returns the label map; _parse_scores takes it as an optional argument)
CALLERS: src/amatelier/engine/roundtable_runner.py -> run_roundtable calls judge_score; src/amatelier/engine/judge_scorer.py -> judge_score calls _format_transcript, _anonymize_text and _parse_scores
DOC_GROUNDING: CLAUDE.md — "Tests required": new code requires new tests; no public symbol or config key is added, so llm/SPEC.md and docs/reference are unchanged
USER_PATH: src/amatelier/engine/roundtable_runner.py run_roundtable -> judge_scorer.judge_score -> judge_scorer._format_transcript -> judge_scorer._call_sonnet
RED_STATE: src/amatelier/engine/judge_scorer.py `_format_transcript()` stops at 1,200 characters per message and 20,000 in total and `judge_score()` sends `briefing_text[:3000]`; on a real five-agent debate of about 60,000 characters the same caps showed the scorer 17 of 31 messages and none of the floor phase
RED_TYPE: USER-OBSERVABLE
GREEN_CONDITION: tests/test_judge_transcript.py passes, showing that _format_transcript returns every phase with a 10,000-character post kept past 1,200 characters, drops a research-window post without a [[request:]] and keeps one with it, labels the judge Moderator and leaves no worker name in the text; that _parse_scores maps reviewer labels back to real names; and that judge_score sends the whole briefing past character 3,000 while its retry names reviewers by label only; `make test` passes
OMISSIONS: the scoring rubric, the 0-1-2-3-10 scale and the calibration text in src/amatelier/engine/judge_scorer.py JUDGE_PROMPT are unchanged; src/amatelier/engine/judge_scorer.py _adversarial_verification() still receives briefing_text[:1000] as a topic line after labels are mapped back
CASE_TRACE:
- case_id: green; finding: the whole debate reaches the scorer blinded, research-window debate is dropped, labels map back, the whole briefing is sent and the retry is blind; trace_run: python -m pytest tests/test_judge_transcript.py; trace_output: tests/test_judge_transcript.py (3 passed; full suite 58 passed); reproducibility: confirmed 2 of 2 runs
- case_id: red; finding: the same tests fail on the committed scorer; trace_run: git stash of judge_scorer.py, pytest tests/test_judge_transcript.py, stash pop; trace_output: tests/test_judge_transcript.py (3 failed); reproducibility: confirmed 1 of 1 runs
FRAME_ASSUMPTIONS:
- A research-window post is legitimate only when it makes a [[request:]]. Reason: the runner opens the window as a pre-debate lookup phase ("--- RESEARCH WINDOW ---") and closes it with "ROUND 1: begin".
SUPPRESSED_PATHS:
- Summarising the debate for the scorer instead of sending it whole. Why suppressed: a summary would be a second model's reading of the debate; the scorer's input travels on stdin with room for the whole transcript.
PREMISE_CHECK: No documented premise.
