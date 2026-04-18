TASK: manual CI — replace auto-trigger with local script
SCOPE: routine
FILES: scripts/ci_local.py (new), Makefile (ci target), .github/workflows/ci.yml, .github/workflows/wheel-smoke.yml, .github/workflows/docs.yml
REPLACES: auto-triggered workflows that burn GitHub Actions minutes on every push/PR — replaced by local script + workflow_dispatch manual-only triggers
MIGRATION: none — existing v* tag triggers preserved on all workflows (release/publish paths unchanged)
CALLERS: developer runs `python scripts/ci_local.py` or `make ci` before pushing. CI workflows callable from Actions UI via workflow_dispatch when needed.
USER_PATH: developer makes code change → runs `python scripts/ci_local.py` locally → script runs ruff + pytest smoke + mkdocs + wheel build + DB integration test sequentially → exits 0 on success, 1 with failure list on failure → developer pushes only if green
RED_STATE: ci.yml/wheel-smoke.yml/docs.yml all had `on: push: branches: [main]` and `pull_request: branches: [main]` — every push/PR triggered ~7min of CI runs per commit. No cross-platform local CI script existed; Makefile targets unusable on Windows without `make`.
RED_TYPE: INFRASTRUCTURE
GREEN_CONDITION: `python scripts/ci_local.py` runs all 5 checks (ruff, pytest smoke, mkdocs, wheel build, pytest integration) on any OS with Python, reports pass/fail per check, exits non-zero on any failure. Pushing to main does NOT fire ci.yml/wheel-smoke.yml/docs.yml. Pushing a `v*` tag DOES fire all of them plus publish.yml + release.yml.
OMISSIONS:
- No Docker / `act` integration — users wanting true CI parity can still run `docker compose run --rm integration` as before
- scripts/ci_local.py does not support parallel execution — runs checks sequentially (acceptable for <10s per check)
- Makefile `ci` target delegates to python script; mac/linux users could bypass this but it's simpler to maintain one implementation
