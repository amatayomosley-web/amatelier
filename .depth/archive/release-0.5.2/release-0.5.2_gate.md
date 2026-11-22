TASK: release-0.5.2
SCOPE: routine
FILES: pyproject.toml, src/amatelier/__init__.py, tests/test_smoke.py, CHANGELOG.md
REPLACES: none — a version-value bump (0.5.0 and 0.5.1 to 0.5.2), no code pattern replaced
MIGRATION: none — no existing callers; __version__ is a constant read by tests/test_smoke.py and .github/workflows/wheel-smoke.yml
CALLERS: none — no new function; the __version__ constant is read by tests/test_smoke.py (test_package_imports) and the wheel-smoke.yml version assert
DOC_GROUNDING: CHANGELOG.md — Keep a Changelog: move [Unreleased] into a dated [0.5.2] section at release
USER_PATH: git tag v0.5.2 push -> .github/workflows/publish.yml -> pip install amatelier==0.5.2 -> src/amatelier/__init__.py:__version__
RED_STATE: src/amatelier/__init__.py:__version__ is "0.5.0" while pyproject.toml says 0.5.1, so wheel-smoke.yml's version assert fails on a tag; PyPI 0.5.1 ships the retired claude-sonnet-4-20250514 default
RED_TYPE: USER-OBSERVABLE
GREEN_CONDITION: pytest tests/test_smoke.py passes with __version__ == "0.5.2"; python -m build produces amatelier-0.5.2 wheel whose installed __version__ returns 0.5.2
OMISSIONS: PR #8 (fix/context-scoring-isolation) is not in this release — it conflicts with main in src/amatelier/llm_backend.py
PREMISE_CHECK: No documented premise.
CASE_TRACE:
- case_id: version-mismatch
  finding: __init__.py says 0.5.0, pyproject says 0.5.1
  trace_location: src/amatelier/__init__.py:37, pyproject.toml:7
FRAME_ASSUMPTIONS:
- pyproject.toml version is the release version. Reason: wheel-smoke.yml asserts __version__ equals it.
SUPPRESSED_PATHS:
- single-sourcing the version via importlib.metadata 
  Why suppressed: a refactor of how the version is read, out of scope for a release bump
