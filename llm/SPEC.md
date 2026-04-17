# Amatelier — Specification

> Canonical machine-readable description. This file is hand-written and authoritative. `llm/API.md` and `llm/SCHEMA.md` are generated from source code; this file is not.

## Identity

- **Name:** amatelier
- **Display name:** Atelier
- **One-liner:** A self-evolving multi-model AI team skill for Claude Code
- **Author:** Maximillian
- **License:** MIT
- **Standard:** Amatayo Standard v1.0

## Repository

- **Source:** https://github.com/amatayomosley-web/amatelier
- **Docs (human):** https://amatayomosley-web.github.io/amatelier/
- **Docs (LLM):** https://raw.githubusercontent.com/amatayomosley-web/amatelier/main/llms-full.txt

## Top-level components

_Populate this section after the first implementation pass. Each component should be exhaustively listed with:_

```yaml
- name: <component>
  path: src/amatelier/<path>
  purpose: <one line>
  public_api: [list of exported symbols]
  depends_on: [other components]
```

## Invariants

1. The package is pip-installable (Python) or npm-installable (Node); never clone-required
2. `llm/` directory is flat — no subdirectories
3. Generated files (`llm/API.md`, `llm/SCHEMA.md`, `llms.txt`, `llms-full.txt`, `.cursor/rules/*`, `.github/copilot-instructions.md`) are rebuilt by CI from canonical sources
4. Public symbols in `src/amatelier/` must be documented in this file
5. CLI flags must appear in both `docs/reference/cli.md` (human) and `llm/API.md` (machine, auto-generated)

## Glossary

_Define project-specific terms here so LLMs consume them deterministically._
