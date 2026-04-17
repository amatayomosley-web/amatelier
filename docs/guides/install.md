# Install

> **Guide** — task-oriented. For a guided walkthrough see [Tutorials](../tutorials/first-run.md). For design rationale see [Explanation](../explanation/architecture.md).

> **Note on naming.** The PyPI package is `amatelier`; the Python import is `amatelier`. This is common practice (e.g. `pip install scikit-learn` → `import sklearn`). All code, docs, and tooling in this repo use `amatelier` as the import name.
Three install paths, depending on what you want to do.

## Consumer — you just want to use it

```bash
pip install amatelier
```

Upgrade:

```bash
pip install -U amatelier
```

Uninstall:

```bash
pip uninstall amatelier
```

## Contributor — you want to hack on it

```bash
git clone https://github.com/amatayomosley-web/amatelier
cd amatelier
pip install -e ".[dev]"
make test
```

`-e` installs in editable mode — changes to source take effect immediately. `[dev]` adds pytest, ruff, mypy.

## DevContainer — you want zero setup

If you have VS Code with the Dev Containers extension, or you're using GitHub Codespaces:

1. Open the repo
2. VS Code: `F1` → "Dev Containers: Reopen in Container"
3. Codespaces: "Code" button → "Codespaces" → "Create"

Everything installs automatically. ~2 minutes to working environment.

## Verify

```bash
amatelier --version
```

## Troubleshooting

See [troubleshooting guide](troubleshooting.md).
