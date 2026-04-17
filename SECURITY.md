# Security Policy

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report them by email to **[INSERT SECURITY CONTACT]** or via GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability).

You should receive an acknowledgement within **48 hours**. After the initial reply, the security team will keep you informed of the progress toward a fix and may ask for additional information.

## What to include

- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Impact assessment
- Any suggested mitigation

## Disclosure policy

- We commit to investigating and patching within **30 days** of a confirmed report
- Coordinated disclosure: we'll publish a security advisory after the fix is released
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
