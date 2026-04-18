"""Local tool implementations for the Steward tool-use loop (open mode).

When amatelier runs via the Anthropic SDK (no claude CLI), the Steward needs
Read / Grep / Glob equivalents implemented in Python. This module provides
them, sandboxed to the workspace root.

Design:
    - `STEWARD_TOOL_SPECS` — Anthropic tool-use schema definitions
    - `dispatch_tool(name, input_dict)` — routes to the concrete function,
      returns a plain string (the shape Anthropic expects in tool_result)
    - All paths resolve under WORKSPACE_ROOT (set by steward_dispatch).
      Paths that resolve outside it are rejected.

Same security posture as claude-code mode with --allowedTools Read,Grep,Glob:
the Steward can read any file under the workspace, including .env files.
Callers who want stricter isolation should set up a restricted workspace.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path

logger = logging.getLogger("steward.tools")


# Soft caps to keep tool outputs bounded (Anthropic cost control)
MAX_FILE_BYTES = 256 * 1024
MAX_GREP_RESULTS = 100
MAX_GLOB_RESULTS = 200


STEWARD_TOOL_SPECS = [
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file from the workspace. Returns the file "
            "contents with line numbers. Truncates at 256KB to bound cost."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace root",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting line number (1-indexed, optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to return (optional, default 500)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search files for a regex pattern. Returns matching lines with "
            "file:line prefix. Caps at 100 matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Python regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory to search, relative to workspace "
                        "root. Defaults to workspace root."
                    ),
                },
                "glob": {
                    "type": "string",
                    "description": (
                        "Optional glob filter to restrict which files are "
                        "searched (e.g. '*.py', '**/*.md')"
                    ),
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default false)",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "glob",
        "description": (
            "List files matching a glob pattern under the workspace root. "
            "Returns up to 200 paths, most-recently-modified first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py', 'docs/*.md')",
                },
            },
            "required": ["pattern"],
        },
    },
]


def _safe_resolve(workspace_root: Path, raw_path: str) -> Path:
    """Resolve a user-supplied path under workspace_root. Reject traversal."""
    if not raw_path or not isinstance(raw_path, str):
        raise ValueError("path must be a non-empty string")
    p = (workspace_root / raw_path).resolve()
    # Must stay within workspace_root after resolution
    try:
        p.relative_to(workspace_root.resolve())
    except ValueError as e:
        raise ValueError(
            f"path escapes workspace root: {raw_path}"
        ) from e
    return p


# Credential denylist — defends against the in-sandbox attack chain
# identified in Security RT digest-afd96c74180e (Elena's Grand Insight):
# "path containment and sensitive-file access are orthogonal concerns".
# Blocks read_file() and grep() against well-known credential-bearing files
# even though they live inside WORKSPACE_ROOT by design.
_SECRET_FILENAMES = frozenset({
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "config",  # only in .ssh and .aws
    "known_hosts",
    "authorized_keys",
})

_SECRET_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".keystore",
    ".jks",
    ".asc",
    ".gpg",
)

_SECRET_NAME_PATTERNS = (
    "_token",
    "_secret",
    "_apikey",
    "_api_key",
    ".env.",  # .env.local, .env.production, etc.
)

_SECRET_DIR_PARENTS = frozenset({
    ".ssh",
    ".aws",
    ".gnupg",
    ".docker",
    ".kube",
})


# Template/example files that LOOK like secrets but are intentionally public.
# .env.example, secrets.template, etc. — readable so the Steward can audit them.
_TEMPLATE_SUFFIXES = (".example", ".template", ".sample", ".dist")


def _is_secret_path(p: Path) -> bool:
    """Return True if `p` looks like a credential or secret-bearing file.

    Filename-based heuristic. Defends in-sandbox secrets even though path
    containment passes. Conservative: blocks more than a strict CVE list
    because false-positive cost (refused read) is much lower than false-
    negative cost (leaked credential into RT digest)."""
    name = p.name
    name_lower = name.lower()

    # Public template files (e.g. .env.example) are not secrets
    if name_lower.endswith(_TEMPLATE_SUFFIXES):
        return False

    # Anything inside a credential-bearing parent directory
    parts_lower = {part.lower() for part in p.parts}
    if parts_lower & _SECRET_DIR_PARENTS:
        return True

    if name_lower in _SECRET_FILENAMES:
        return True

    if name_lower.endswith(_SECRET_SUFFIXES):
        return True

    if any(token in name_lower for token in _SECRET_NAME_PATTERNS):
        return True

    return False


def _block_message(p: Path, workspace_root: Path) -> str:
    try:
        rel = p.relative_to(workspace_root).as_posix()
    except ValueError:
        rel = p.name
    return (
        f"Error: blocked secret-path '{rel}' (Steward credential denylist). "
        f"This file matches a known credential pattern and cannot be read."
    )


def read_file(
    workspace_root: Path,
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read a file with optional line range, bounded by MAX_FILE_BYTES."""
    p = _safe_resolve(workspace_root, path)
    if _is_secret_path(p):
        return _block_message(p, workspace_root)
    if not p.exists():
        return f"Error: file not found: {path}"
    if not p.is_file():
        return f"Error: not a file: {path}"
    try:
        data = p.read_bytes()[:MAX_FILE_BYTES]
        text = data.decode("utf-8", errors="replace")
    except OSError as e:
        return f"Error: cannot read {path}: {e}"

    lines = text.splitlines()
    start = (offset or 1) - 1
    if start < 0:
        start = 0
    end = start + (limit or 500)
    slice_ = lines[start:end]
    # cat -n style for lookups
    numbered = "\n".join(
        f"{i + start + 1:5}\t{line}" for i, line in enumerate(slice_)
    )
    total = len(lines)
    suffix = ""
    if end < total:
        suffix = f"\n... [truncated at line {end} of {total}]"
    return numbered + suffix


def grep(
    workspace_root: Path,
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    ignore_case: bool = False,
) -> str:
    """Search files for a regex pattern."""
    try:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: invalid regex '{pattern}': {e}"

    base = workspace_root
    if path:
        try:
            base = _safe_resolve(workspace_root, path)
        except ValueError as e:
            return f"Error: {e}"
    if not base.exists():
        return f"Error: path not found: {path or '.'}"

    candidates: list[Path]
    if base.is_file():
        candidates = [base]
    else:
        pat = glob or "**/*"
        candidates = [
            q for q in base.glob(pat)
            if q.is_file() and not _skip_file(q)
        ]

    matches: list[str] = []
    for q in candidates:
        if len(matches) >= MAX_GREP_RESULTS:
            break
        # Skip credential-bearing files even if they match the glob
        if _is_secret_path(q):
            continue
        try:
            with q.open("r", encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if regex.search(line):
                        rel = q.relative_to(workspace_root).as_posix()
                        matches.append(f"{rel}:{n}:{line.rstrip()}")
                        if len(matches) >= MAX_GREP_RESULTS:
                            matches.append(
                                f"... [truncated at {MAX_GREP_RESULTS} matches]"
                            )
                            break
        except OSError:
            continue

    if not matches:
        return f"No matches for pattern: {pattern}"
    return "\n".join(matches)


def glob_search(workspace_root: Path, pattern: str) -> str:
    """List files matching the glob, most-recently-modified first."""
    if not pattern:
        return "Error: pattern is required"
    # fnmatch is unsafe for absolute patterns; normalize to relative
    try:
        hits = [
            q for q in workspace_root.glob(pattern)
            if q.is_file() and not _skip_file(q)
        ]
    except (OSError, ValueError) as e:
        return f"Error: bad glob pattern '{pattern}': {e}"
    hits.sort(key=lambda q: q.stat().st_mtime, reverse=True)
    hits = hits[:MAX_GLOB_RESULTS]
    if not hits:
        return f"No files match: {pattern}"
    return "\n".join(q.relative_to(workspace_root).as_posix() for q in hits)


def _skip_file(p: Path) -> bool:
    """Skip binary / vendor / build directories."""
    parts = set(p.parts)
    SKIP_DIRS = {
        ".git", ".venv", "venv", "__pycache__", "node_modules",
        "dist", "build", "site", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".depth",
    }
    if parts & SKIP_DIRS:
        return True
    # Skip obvious binaries
    if p.suffix.lower() in {".pyc", ".pyo", ".so", ".dll", ".exe",
                             ".db", ".sqlite", ".png", ".jpg", ".jpeg",
                             ".gif", ".ico", ".pdf", ".zip", ".gz"}:
        return True
    return False


def dispatch_tool(
    workspace_root: Path,
    name: str,
    input_dict: dict,
) -> str:
    """Execute a tool by name with the given input dict. Returns text result."""
    try:
        if name == "read_file":
            return read_file(
                workspace_root,
                path=input_dict["path"],
                offset=input_dict.get("offset"),
                limit=input_dict.get("limit"),
            )
        if name == "grep":
            return grep(
                workspace_root,
                pattern=input_dict["pattern"],
                path=input_dict.get("path"),
                glob=input_dict.get("glob"),
                ignore_case=bool(input_dict.get("ignore_case", False)),
            )
        if name == "glob":
            return glob_search(
                workspace_root,
                pattern=input_dict["pattern"],
            )
        return f"Error: unknown tool '{name}'"
    except KeyError as e:
        return f"Error: missing required field: {e}"
    except Exception as e:  # noqa: BLE001
        logger.warning("steward tool %s raised: %s", name, e)
        return f"Error: tool '{name}' failed: {e}"
