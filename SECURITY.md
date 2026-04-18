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
