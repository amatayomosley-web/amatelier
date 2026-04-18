# Security Policy

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Report suspected vulnerabilities via **[GitHub's private vulnerability reporting](https://github.com/amatayomosley-web/amatelier/security/advisories/new)**. This is the primary and preferred channel.

No public email is maintained for security reports. If you cannot use GitHub's advisory form (for example, the issue is in the reporting pipeline itself), open a minimal private notice via [GitHub Discussions](https://github.com/amatayomosley-web/amatelier/discussions) asking a maintainer to contact you; do not include vulnerability details in the public thread.

You should receive an acknowledgement within **48 hours**. After the initial reply, maintainers will keep you informed of the progress toward a fix and may ask for additional information.

## What to include

- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Impact assessment
- Any suggested mitigation

## Scope of reports

**In scope:**

- Code execution via `amatelier` (CLI, library, or bundled entry points)
- Credential leakage (API keys, tokens, session artifacts) through logs, digests, or generated files
- Prompt injection via briefing files or other user-supplied content processed by agents
- Path traversal or arbitrary file access in `amatelier.paths.user_data_dir()` and related helpers
- Privilege escalation across the dual-layer path boundary (bundled vs. user data)

**Out of scope:**

- Social engineering of maintainers or contributors
- Denial of service against agents running under your own account, API key, or local machine
- Spend exhaustion from your own API key (set provider-side budgets)
- Vulnerabilities in upstream SDKs (`anthropic`, `openai`, `google-genai`, `platformdirs`, etc.) — please report those to the respective upstream projects
- Issues that require a pre-compromised local environment or physical access

## Disclosure policy

- We commit to investigating and patching confirmed reports within **30 days**
- Coordinated disclosure: we publish a security advisory after the fix is released
- Credit is given to reporters in the advisory unless they request anonymity

## Supported versions

| Version | Supported |
|---------|-----------|
| Latest major | Yes |
| Previous major | Security fixes only |
| Older | No |

## Security measures in this project

- Branch protection on `main` — all changes go through reviewed PRs
- Dependabot enabled for dependency and GitHub Actions updates
- Secret scanning with push protection enabled
- CodeQL static analysis runs on every PR
- Signed releases via sigstore/cosign
- Steward credential denylist — `.env`, `.ssh/`, `.aws/`, `*.pem`,
  `*.key`, token/secret patterns blocked at `read_file()` even when
  path containment passes
- Steward result truncation at 4 KB before digest persistence
- Runtime consent gate — first `amatelier roundtable` call prompts
  for explicit consent (or honors `AMATELIER_STEWARD_CONSENT=1` in CI)

## Subagent Permission Inheritance (operational security note)

When you run `amatelier roundtable`, the runner spawns several
subprocesses (workers Elena/Marcus/Clare/Simon/Naomi, the Judge, and
the Steward). These subprocesses **inherit the Claude Code permission
context of the working directory the runner was launched from** —
specifically:

- Worker/judge spawn via `subprocess.Popen([python, engine/claude_agent.py, ...])` from the runner's CWD
- When those subprocesses invoke `claude` (claude-code mode), Claude
  Code reads `.claude/settings.json` and `.claude/settings.local.json`
  **relative to the spawning CWD**, not relative to `AMATELIER_WORKSPACE`
- The Steward runs with `--allowedTools Read,Grep,Glob[,WebFetch,WebSearch]`
  and `--dangerously-skip-permissions` — its filesystem reach is the
  CWD's workspace, not a separate sandbox

**Practical implications for users running RTs:**

1. If you run amatelier from a directory whose `.claude/settings.local.json`
   grants broad `Read`/`Edit`/`Write` permissions, subagents inherit
   that reach. A compromised briefing can prompt-inject workers into
   reading anything those permissions allow.
2. Set `AMATELIER_WORKSPACE` to a clean, bounded subdirectory for
   audit / untrusted-briefing RTs.
3. The credential denylist + truncation + consent gate defend against
   the most common exfiltration paths (reading `.env`, writing
   full-file contents to the RT digest) but do not replace proper
   workspace isolation.
4. Do not run amatelier from your home directory or project root if
   the directory contains secrets you don't want the model to see.

This is the same security posture as running `claude` directly —
subagents are not a separate sandbox.
