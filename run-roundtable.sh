#!/usr/bin/env bash
# Convenience wrapper for Admin to call the roundtable runner.
# Usage: bash .claude/skills/claude-suite/run-roundtable.sh --topic "..." --briefing briefing-xxx.md [options]
#
# All arguments are passed through to roundtable_runner.py.
# The .env file is loaded automatically for Gemini API key.

set -euo pipefail

SUITE_DIR="$(cd "$(dirname "$0")" && pwd)"

exec python "$SUITE_DIR/engine/roundtable_runner.py" "$@"
