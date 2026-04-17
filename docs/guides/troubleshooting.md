# Troubleshooting

> **Guide** — lookup table of common errors and fixes.

## `command not found: atelier`

Pip installed the package but the CLI isn't on your `PATH`. Check:

```bash
python -m atelier --version
```

If that works, the script location isn't on `PATH`. Usually fixed by:

```bash
pip install --user atelier
# and then ensure ~/.local/bin is on PATH
```

## `ModuleNotFoundError` after editable install

You probably installed with `pip install .` instead of `pip install -e .`. Uninstall and reinstall:

```bash
pip uninstall atelier
pip install -e ".[dev]"
```

## Tests fail with import errors

Make sure you installed with the `dev` extras:

```bash
pip install -e ".[dev]"
```

## Still stuck

- Search [existing issues](https://github.com/amatayomosley-web/atelier/issues)
- Open a new issue with the bug report template
