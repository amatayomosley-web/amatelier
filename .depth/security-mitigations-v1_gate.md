TASK: apply Security RT v2 mandatory mitigations (#2, #3, #4)
SCOPE: critical
FILES: src/amatelier/engine/steward_tools.py, src/amatelier/engine/steward_dispatch.py, src/amatelier/cli.py, src/amatelier/paths.py
REPLACES: three security holes confirmed by Security RT digest-afd96c74180e and Elena's Grand Insight ("path containment and sensitive-file access are orthogonal concerns, and only the first is defended"):
  1. steward_tools.read_file() has no credential denylist — agents can request `.env`, `.git/config`, `~/.aws/credentials` and they pass _safe_resolve() because they're inside WORKSPACE_ROOT
  2. steward_dispatch.format_result() returns full result text and runner persists it to digest + steward-log JSON — credentials read once exfiltrate to durable artifacts
  3. spawn_steward_subagent() executes on first dispatch with no user consent moment — GDPR Article 13 requires disclosure before processing event, not at install time
MIGRATION: Existing CI/automation that runs amatelier roundtables must set AMATELIER_STEWARD_CONSENT=1 to skip the runtime prompt; documented in CHANGELOG and .env.example.
CALLERS:
  - steward_tools.read_file() — called from dispatch_tool() during anthropic-sdk Steward tool-use loop
  - steward_dispatch.format_result() — called from runner research-window phase
  - steward_dispatch.spawn_steward_subagent() — called from runner research-window + per-round dispatch
  - cli.py existing roundtable subcommand — gains pre-flight consent check
USER_PATH: developer runs `amatelier roundtable` → CLI checks AMATELIER_STEWARD_CONSENT env or prior accept → if neither, prints disclosure + prompts for y/n → on consent, sets process env var for child processes → runner enters research window → agents emit `[[request: read .env]]` → steward dispatch resolves to read_file('.env') → _is_secret_path(p) returns True → returns "Error: blocked secret-path .env (Steward denylist)" → result truncated to 4KB at format_result + persisted truncated to digest → no credential ever transits to Anthropic API or persists to disk artifact
RED_STATE:
  - steward_tools.py:140-152 read_file() opens any path that passes _safe_resolve(). No filename or extension check.
  - steward_dispatch.py:419-422 format_result() returns the full result['result'] string for runner injection.
  - roundtable_runner.py around line 590 db_cmd("speak", "runner", inject_msg) writes full text to messages table → digest persistence.
  - StewardLog.record() at steward_dispatch.py around line 440 writes full result to steward-log JSON.
  - cli.py roundtable command spawns runner immediately on invocation. No consent moment.
RED_TYPE: USER-OBSERVABLE (privacy + security harm to end users)
GREEN_CONDITION:
  - steward_tools._is_secret_path(p) blocks: `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa`, `id_ed25519`, `credentials`, `.git/config`, `.aws/credentials`, `.netrc`, `.npmrc`, `.pypirc`, anything ending in `_token` or `_secret` or `_key` (case-insensitive). read_file() and grep() return "Error: blocked secret-path..." string instead of content.
  - format_result() truncates the result text at 4096 chars before injection, prepending a `[truncated to 4KB]` marker if needed.
  - StewardLog.record() truncates the persisted result text at 4096 chars.
  - First spawn_steward_subagent() call per amatelier process checks env AMATELIER_STEWARD_CONSENT in {"1","yes","true"}; if missing, raises SteWardConsentRequired with a documented message; cli.py catches the exception, prompts the user with a clear disclosure (sends file content excerpts to claude/anthropic API), and sets AMATELIER_STEWARD_CONSENT=1 for the current process if user accepts.
  - All four checks have unit-test-style verification by directly invoking _is_secret_path() with a fixture list, calling format_result() with oversize string, and calling spawn_steward_subagent() with the env var unset.
OMISSIONS:
  - The denylist is filename-pattern based, not content-scanned. A user-renamed credential file (e.g. mysecret.txt) is not blocked — documented as known limitation.
  - The truncation length is hardcoded 4096; not yet exposed in config.json. A future RT can tune.
  - Consent is per-process not persistent — restarting amatelier re-prompts. Persistent consent (a checkbox in user_data_dir) deferred.
  - Steward in claude-code mode (subprocess CLI) gets the truncation but not the read_file denylist — denylist runs in the SDK tool-use path only. CLI mode uses the actual claude binary's Read tool which has its own surface. This is documented as deferred — claude-code Steward limitation.
  - openai-compat backend already returns "unavailable" for Steward; mitigations don't apply there.
