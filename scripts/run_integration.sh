#!/usr/bin/env bash
# Run the integration test suite locally.
#
# Prefers Docker for Linux parity with CI. Falls back to a local venv
# if Docker Desktop isn't running. Either way, runs the same
# tests/test_db_integration.py against the real migrations and
# seeded fixture data.
#
# Usage:
#   bash scripts/run_integration.sh              # auto-detect: Docker or venv
#   bash scripts/run_integration.sh --docker     # force Docker
#   bash scripts/run_integration.sh --venv       # force venv
#   bash scripts/run_integration.sh --shell      # drop into a shell in Docker

set -euo pipefail

cd "$(dirname "$0")/.."

MODE="auto"
case "${1:-}" in
  --docker) MODE="docker" ;;
  --venv)   MODE="venv" ;;
  --shell)  MODE="shell" ;;
  --help|-h)
    sed -n '2,14p' "$0"
    exit 0
    ;;
esac

docker_available() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

run_docker() {
  echo "==> Integration test in Docker (Linux parity with CI)"
  docker build -q -t amatelier-test . >/dev/null
  docker run --rm amatelier-test
}

run_docker_shell() {
  echo "==> Docker shell"
  docker build -q -t amatelier-test . >/dev/null
  docker run --rm -it amatelier-test bash
}

run_venv() {
  echo "==> Integration test in local venv"
  VENV_DIR=".venv-integration"
  if [[ ! -d "$VENV_DIR" ]]; then
    python -m venv "$VENV_DIR"
  fi
  # Detect venv bin path (Windows = Scripts, Unix = bin)
  if [[ -f "$VENV_DIR/Scripts/python.exe" ]]; then
    PY="$VENV_DIR/Scripts/python.exe"
    PIP="$VENV_DIR/Scripts/pip.exe"
  else
    PY="$VENV_DIR/bin/python"
    PIP="$VENV_DIR/bin/pip"
  fi
  # Upgrading pip via pip itself fails on Windows due to file locks;
  # use `python -m pip` + tolerate the "cannot modify pip while running" error.
  "$PY" -m pip install --quiet --upgrade pip 2>/dev/null || true
  "$PY" -m pip install --quiet -e ".[dev]"
  "$PY" -m pytest tests/test_db_integration.py -v --tb=short
}

case "$MODE" in
  docker)
    run_docker
    ;;
  shell)
    run_docker_shell
    ;;
  venv)
    run_venv
    ;;
  auto)
    if docker_available; then
      run_docker
    else
      echo "(Docker Desktop not running — falling back to venv)"
      run_venv
    fi
    ;;
esac
