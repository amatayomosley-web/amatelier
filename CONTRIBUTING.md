# Contributing to Atelier

Thanks for your interest in improving this project.

## Before you start

1. Search [existing issues](https://github.com/amatayomosley-web/atelier/issues) to avoid duplicates
2. For significant changes, open an issue first to discuss the approach
3. Read the [Code of Conduct](CODE_OF_CONDUCT.md)

## Dev setup

```bash
git clone https://github.com/amatayomosley-web/atelier
cd atelier
make setup      # installs package + dev deps editable
make test       # runs pytest
make lint       # ruff + mypy
make demo       # runs examples/first_run/
```

Or open the repo in a DevContainer / GitHub Codespace — the `.devcontainer/` config handles everything automatically.

## Pull request workflow

1. Fork the repo and create a feature branch: `git checkout -b feat/my-thing`
2. Make focused commits using [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: add new capability`
   - `fix: correct behavior of X`
   - `docs: clarify installation`
   - `BREAKING CHANGE: describe the break`
3. Keep PRs small — one logical change per PR
4. Ensure `make lint && make test` passes locally
5. Open the PR against `main`; fill the PR template

## Code style

- Ruff handles formatting and linting (`make format` to fix)
- Type hints required on public APIs (`mypy --strict`)
- Keep files under 500 lines
- Write tests for new code; aim for ≥80% coverage

## Releases

Releases are fully automated on tag push. Maintainers run:

```bash
git tag v0.2.0
git push --tags
```

CI then publishes to PyPI (via trusted publishing) and creates a signed GitHub Release.

## Enabling branch protection (maintainers)

Once the repo is created, enable these in Settings → Branches → `main`:

- Require pull request reviews (at least 1)
- Require status checks to pass (`test`, `build-check`)
- Require signed commits (recommended)
- Require linear history
- Block force pushes
