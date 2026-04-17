"""Steward Dispatch — empirical grounding for roundtable debates.

The Steward is an ephemeral subagent spawned by the runner on behalf of
debaters who request data via [[request: ...]] tags. The Judge routes
requests by rewriting them into precise lookup instructions via DISPATCH.

Two execution paths:
  - Deterministic: JSON filters, grep, value extraction (no model call)
  - Subagent: Code navigation, fuzzy requests (Haiku or Sonnet via claude -p)

Design doc: STEWARD.md in suite root.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("steward")

ENGINE_DIR = Path(__file__).resolve().parent
SUITE_ROOT = ENGINE_DIR.parent
# Workspace root = where the user actually runs commands from. When installed
# at .claude/skills/claude-suite, ascending three levels from SUITE_ROOT lands
# in the project workspace (skill -> skills -> .claude -> project). The
# AMATELIER_WORKSPACE env var overrides this when the layout differs.
_env_workspace = os.environ.get("AMATELIER_WORKSPACE", "").strip()
if _env_workspace:
    WORKSPACE_ROOT = Path(_env_workspace).resolve()
else:
    WORKSPACE_ROOT = SUITE_ROOT.parent.parent.parent

# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

REQUEST_RE = re.compile(
    r"\[\[request:\s*(.*?)\]\]",
    re.DOTALL | re.IGNORECASE,
)


def parse_requests(message: str) -> list[str]:
    """Extract all [[request: ...]] blocks from an agent's message.

    Returns the raw request text (natural language) for each block.
    """
    return [m.strip() for m in REQUEST_RE.findall(message) if m.strip()]


def strip_requests(message: str) -> str:
    """Return the message with [[request:]] blocks removed (for transcript)."""
    return REQUEST_RE.sub("", message).strip()


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------

class StewardBudget:
    """Per-agent, per-RT request budget."""

    def __init__(self, agents: list[str], budget_per_agent: int = 3):
        self._budget = {a: budget_per_agent for a in agents}
        self._log: list[dict] = []

    def remaining(self, agent: str) -> int:
        return self._budget.get(agent, 0)

    def spend(self, agent: str, request: str) -> bool:
        """Deduct 1 from agent's budget. Returns False if out of budget."""
        if self._budget.get(agent, 0) <= 0:
            return False
        self._budget[agent] -= 1
        self._log.append({
            "agent": agent,
            "request": request,
            "remaining": self._budget[agent],
            "timestamp": time.time(),
        })
        return True

    def status(self) -> dict[str, int]:
        return dict(self._budget)

    @property
    def log(self) -> list[dict]:
        return list(self._log)


# ---------------------------------------------------------------------------
# Registered files
# ---------------------------------------------------------------------------

def load_registered_files(briefing_path: str) -> list[str]:
    """Parse the briefing for a '## Steward-Registered Files' section.

    Returns list of file paths (relative to workspace root).
    If no section found, returns empty list (Steward disabled for this RT).
    """
    try:
        text = Path(briefing_path).read_text(encoding="utf-8")
    except Exception:
        return []

    # Look for the section header
    in_section = False
    files: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## steward") and "file" in stripped.lower():
            in_section = True
            continue
        if in_section:
            if stripped.startswith("##"):
                break  # Next section
            if stripped.startswith("- "):
                # Extract path, strip parenthetical notes
                path = stripped[2:].split("(")[0].strip().rstrip("*")
                if path:
                    files.append(path)
    return files


def resolve_file(path: str, registered: list[str]) -> str | None:
    """Check if a file path (or glob) is in the registered list.

    Returns the resolved absolute path, or None if not registered.
    Supports glob matching for patterns like 'staging/diagnostic-probe/*.json'.
    """
    import glob as glob_mod

    for reg in registered:
        if "*" in reg:
            matches = glob_mod.glob(str(WORKSPACE_ROOT / reg))
            abs_path = str(WORKSPACE_ROOT / path)
            if abs_path in matches:
                return abs_path
        elif path == reg or path.endswith(reg) or reg.endswith(path):
            full = WORKSPACE_ROOT / reg
            if full.exists():
                return str(full)
    return None


# ---------------------------------------------------------------------------
# Deterministic execution (no model call)
# ---------------------------------------------------------------------------

def try_deterministic(request: str, registered: list[str]) -> str | None:
    """Attempt to handle the request without an LLM.

    Returns the result string if handled, None if it needs a subagent.
    Handles:
      - Exact value lookups: "value of X in file Y"
      - Grep: "grep X in file Y"
      - JSON count/filter: "count rows where X in file Y"
    """
    req_lower = request.lower()

    # Pattern: count/how many ... where ... in <file>
    count_match = re.search(
        r"(?:count|how many).*?(?:where|matching|with)\s+(\w+)\s*[=!<>]+\s*['\"]?(\w+)['\"]?"
        r".*?(?:in|from)\s+(\S+\.json)",
        req_lower,
    )
    if count_match:
        field, value, filename = count_match.groups()
        filepath = resolve_file(filename, registered)
        if filepath:
            try:
                data = json.loads(Path(filepath).read_text(encoding="utf-8"))
                if isinstance(data, dict) and "results" in data:
                    data = data["results"]
                if isinstance(data, list):
                    # Case-insensitive key matching (JSON camelCase vs lowercase)
                    def _get_ci(row: dict, key: str):
                        for k, v in row.items():
                            if k.lower() == key.lower():
                                return str(v)
                        return ""
                    matches = [r for r in data if _get_ci(r, field).lower() == value.lower()]
                    return f"[Deterministic | {filename}]: {len(matches)} rows match {field}=={value} (of {len(data)} total)."
            except Exception as e:
                logger.warning("Deterministic count failed: %s", e)

    # Pattern: "value of X in <file>" or "what is X in <file>"
    value_match = re.search(
        r"(?:value of|what is|show me)\s+[`'\"]?(\w+)[`'\"]?\s+(?:in|from)\s+(\S+)",
        req_lower,
    )
    if value_match:
        key, filename = value_match.groups()
        filepath = resolve_file(filename, registered)
        if filepath:
            try:
                content = Path(filepath).read_text(encoding="utf-8")
                # Search for assignment patterns: key = value, "key": value
                patterns = [
                    rf"{key}\s*[:=]\s*(.+?)(?:;|,|\n)",
                    rf'"{key}"\s*:\s*(.+?)(?:,|\n|\}})',
                ]
                for pat in patterns:
                    m = re.search(pat, content, re.IGNORECASE)
                    if m:
                        val = m.group(1).strip().rstrip(",;")
                        # Find line number
                        pos = m.start()
                        line_num = content[:pos].count("\n") + 1
                        return f"[Deterministic | {filename}:{line_num}]: {key} = {val}"
            except Exception as e:
                logger.warning("Deterministic value failed: %s", e)

    return None  # Needs a subagent


# ---------------------------------------------------------------------------
# Subagent execution (LLM with file tools)
# ---------------------------------------------------------------------------

STEWARD_SYSTEM_PROMPT = """You are a research assistant for a roundtable debate. You have access to project files via Read, Grep, and Glob tools. Your job:

1. Execute the lookup described below.
2. Return ONLY the relevant extract — no interpretation, no opinions, no theorizing.
3. Include file path and line numbers for every code extract.
4. Stay under {max_tokens} tokens.
5. If you cannot find it, say "Not found" and list what you checked.
6. NEVER guess or approximate. Only return what you actually read from files.

Registered files for this RT:
{file_list}

The project root is: {workspace_root}
"""


def spawn_steward_subagent(
    request: str,
    registered_files: list[str],
    model: str = "haiku",
    timeout: int = 120,
    max_tokens: int = 2000,
) -> dict:
    """Spawn an ephemeral Claude subagent with file tools to execute a lookup.

    Returns: {"status": "success"|"timeout"|"error", "result": str, "elapsed_s": float}
    """
    file_list = "\n".join(f"  - {f}" for f in registered_files)
    system = STEWARD_SYSTEM_PROMPT.format(
        max_tokens=max_tokens,
        file_list=file_list,
        workspace_root=str(WORKSPACE_ROOT),
    )

    prompt = f"Lookup request:\n{request}"

    # Map model shorthand to full model ID
    model_map = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-20250514",
    }
    model_id = model_map.get(model, model)

    agent_def = json.dumps({
        "steward": {
            "description": "Ephemeral research assistant for roundtable debates",
            "prompt": system[:8000],
        }
    })

    cmd = [
        "claude",
        "-p",
        "--model", model_id,
        "--agent", "steward",
        "--agents", agent_def,
        "--no-session-persistence",
        "--output-format", "text",
        "--disable-slash-commands",
        "--dangerously-skip-permissions",
        "--max-budget-usd", "2.00",
        "--allowedTools", "Read,Grep,Glob",
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE_ROOT),
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        elapsed = time.monotonic() - start

        if result.returncode != 0:
            logger.warning("Steward subagent failed (exit %d): %s",
                           result.returncode, result.stderr[:300])
            return {
                "status": "error",
                "result": f"Steward lookup failed: {result.stderr[:200]}",
                "elapsed_s": round(elapsed, 2),
            }

        output = result.stdout.strip()
        # Truncate to max_tokens worth of characters (~4 chars/token)
        char_limit = max_tokens * 4
        if len(output) > char_limit:
            output = output[:char_limit] + "\n... [truncated]"

        return {
            "status": "success",
            "result": output,
            "elapsed_s": round(elapsed, 2),
        }

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        logger.warning("Steward subagent timed out after %ds", timeout)
        return {
            "status": "timeout",
            "result": f"Steward lookup timed out after {timeout}s.",
            "elapsed_s": round(elapsed, 2),
        }
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "status": "error",
            "result": f"Steward dispatch error: {e}",
            "elapsed_s": round(elapsed, 2),
        }


# ---------------------------------------------------------------------------
# Async dispatch (threaded)
# ---------------------------------------------------------------------------

class StewardTask:
    """A single async Steward lookup running in a background thread."""

    def __init__(self, agent: str, request: str, registered_files: list[str],
                 config: dict):
        self.agent = agent
        self.request = request
        self.registered_files = registered_files
        self.config = config
        self.result: dict | None = None
        self.done = threading.Event()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # Try deterministic first
        det = try_deterministic(self.request, self.registered_files)
        if det:
            self.result = {
                "status": "success",
                "result": det,
                "elapsed_s": 0.0,
                "model": "deterministic",
            }
            self.done.set()
            return

        # Subagent
        model = self.config.get("steward", {}).get("haiku_model", "haiku")
        timeout = self.config.get("steward", {}).get("timeout_seconds", 120)
        max_tokens = self.config.get("steward", {}).get("max_response_tokens", 2000)

        self.result = spawn_steward_subagent(
            self.request,
            self.registered_files,
            model=model,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        self.result["model"] = model
        self.done.set()

    def wait(self, timeout: float = 130.0) -> dict:
        self.done.wait(timeout=timeout)
        return self.result or {
            "status": "timeout",
            "result": "Steward task did not complete.",
            "elapsed_s": timeout,
        }


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def format_result(agent: str, request: str, result: dict) -> str:
    """Format a Steward result for injection into the debate context."""
    model = result.get("model", "unknown")
    elapsed = result.get("elapsed_s", 0)
    status = result.get("status", "error")

    if status == "success":
        return (
            f"[Research result for {agent} | {model} | {elapsed:.1f}s]:\n"
            f"{result['result']}"
        )
    elif status == "timeout":
        return (
            f"[Research result for {agent} | TIMEOUT after {elapsed:.0f}s]:\n"
            f"The lookup did not complete in time. Try a more specific request."
        )
    else:
        return (
            f"[Research result for {agent} | ERROR]:\n"
            f"{result.get('result', 'Unknown error')}"
        )


# ---------------------------------------------------------------------------
# Steward log (saved alongside digest)
# ---------------------------------------------------------------------------

class StewardLog:
    """Tracks all Steward requests and results for an RT."""

    def __init__(self):
        self._entries: list[dict] = []

    def record(self, agent: str, request: str, result: dict,
               round_num: int = 0):
        self._entries.append({
            "agent": agent,
            "round": round_num,
            "request": request,
            "model": result.get("model", "unknown"),
            "status": result.get("status", "error"),
            "elapsed_s": result.get("elapsed_s", 0),
            "result_preview": result.get("result", "")[:500],
            "timestamp": time.time(),
        })

    def save(self, path: str):
        Path(path).write_text(
            json.dumps(self._entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def entries(self) -> list[dict]:
        return list(self._entries)
