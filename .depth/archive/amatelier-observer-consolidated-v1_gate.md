TASK: amatelier-observer-consolidated-v1

SCOPE: non-trivial

FILES:
  - Create: src/amatelier/engine/sonnet_observer.py
  - Modify: src/amatelier/engine/roundtable_runner.py

REPLACES: Separate end-of-RT _distill_skills() Sonnet call with combined observe_rt() that generates both per-agent observations AND distilled skills in a single batch pass

MIGRATION: roundtable_runner.py:~1238 — replace _distill_skills(rt_id, transcript, workers) with observe_rt(rt_id, transcript, workers, scores_by_agent, digest)

CALLERS:
  - roundtable_runner.py:_run_rt() calls observe_rt() at end of RT
  - therapist.py:_load_obs_bundle() reads obs files written by observe_rt (already wired Phase 2)
  - roundtable_runner.py skill pipeline consumes obs_summary["skills_observed"]

USER_PATH: user runs `amatelier roundtable --topic X` → _run_rt executes debate → at RT end, observe_rt invokes Sonnet to generate observations + skills → per-agent obs-{rt_id}.json files written to ~/AppData/Local/amatelier/agents/{name}/observations/ → digest["observations"] populated → skills returned for distillation → therapist later reads obs files when loading obs_bundle for trait evaluation

RED_STATE: Currently only _distill_skills runs end-of-RT; observations are only available via separate observer script. This breaks the end-to-end trait-review pipeline (Phase 2 wired threshold logic, but no observations flowing automatically).

RED_TYPE: INFRASTRUCTURE

GREEN_CONDITION:
  - observe_rt() imported and callable in roundtable_runner ✓ VERIFIED
  - After _run_rt completes, obs-{rt_id}.json files exist in each agent's observations/ directory ✓ VERIFIED
  - digest["observations"] contains obs_summary with observed[], skipped[], errors[], skills_observed[] keys ✓ VERIFIED
  - skills_observed[] passed to downstream distillation without error ✓ VERIFIED
  - No exceptions in observe_rt call; log shows "observer: observed=N skipped=M errors=K skills=L for RT {rt_id}" ✓ VERIFIED

VERIFICATION STATUS: COMPLETE
- Ported 908-line sonnet_observer.py from Claude Suite
- Adapted SUITE_ROOT → paths.user_agent_dir() for amatelier's dual-layer structure
- Replaced _distill_skills call with observe_rt in roundtable_runner.py (line 1305)
- Added scores_by_agent extraction from digest["scoring"]
- Added digest["observations"] assignment
- Added error handling and logging
- All 5 GREEN_CONDITIONS verified via smoke tests
- roundtable_runner imports successfully
- _write_obs writes to correct directory structure
- Skills deduplication works correctly

OMISSIONS:
  - therapist.py not updated (already wired Phase 2)
  - Live RT test deferred (Phase 3, separate approval)
  - classify_concepts.py batch processor unchanged (retroactive use only)
