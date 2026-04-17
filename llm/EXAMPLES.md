# Examples

> Tested, copy-runnable examples covering the full API surface. Hand-written. CI extracts code blocks and executes them — broken example = red build.

## Conventions

- Each example is a named heading
- Each example is self-contained (can be copy-pasted and run without other context)
- Code blocks have the language tag so the extractor can route them correctly
- Expected output is shown in a second code block tagged `text`
- Prerequisites are listed at the top of each example

## Example: hello world

**Prerequisites:** `pip install amatelier`

```python
from atelier import hello

print(hello("world"))
```

Expected output:

```text
Hello, world!
```

## Example: _add more examples covering every public symbol_

_At scaffold time only the hello-world example ships. dual-docs-architect ensures coverage parity with `llm/API.md`._
