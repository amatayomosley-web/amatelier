# Workflows

> Turn-by-turn orchestration paths. Hand-written. Copied from `docs/explanation/` narrative into this deterministic form by `dual-docs-architect`.

## Conventions

- Each workflow is a named section
- Steps are numbered
- Each step names the file and function responsible
- Inputs and outputs are explicit
- Failure modes are listed at the end of each workflow

## Workflow: primary user path

_Populate after initial implementation._

```yaml
name: <workflow-name>
trigger: <what starts it>
steps:
  - step: 1
    actor: <file:function>
    input: <inputs>
    output: <outputs>
    description: <one line>
  # ...
failure_modes:
  - condition: <what goes wrong>
    behavior: <how it surfaces>
    recovery: <what to do>
```
