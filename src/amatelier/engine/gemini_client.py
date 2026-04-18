"""Shared Gemini API client — used by gemini_agent.py and therapist.py.

Provides:
- Client initialization with .env loading
- call_gemini() with retries, rate limiting, and detailed error logging
- Model name from config.json

All Gemini errors are logged with full context — no more black boxes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("gemini_client")

SUITE_ROOT = Path(__file__).resolve().parent.parent

# Amatayo Standard dual-layer paths: bundled assets stay in SUITE_ROOT
# (read-only post-install); mutable runtime state goes to WRITE_ROOT.
try:
    from amatelier import paths as _amatelier_paths
    _amatelier_paths.ensure_user_data()
    WRITE_ROOT = _amatelier_paths.user_data_dir()
except Exception:
    WRITE_ROOT = SUITE_ROOT

WORKSPACE_ROOT = SUITE_ROOT.parent.parent.parent
CONFIG_PATH = SUITE_ROOT / "config.json"
LOG_DIR = WRITE_ROOT / "roundtable-server" / "logs"

_gemini_client = None
_last_call_time = 0.0
_file_handler_attached = False
MIN_CALL_INTERVAL = 5.0  # seconds between calls — preview rate limits are tight


def _ensure_file_logging():
    """Attach a file handler so Gemini errors are always captured to disk."""
    global _file_handler_attached
    if _file_handler_attached:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(
            str(LOG_DIR / "gemini_errors.log"), encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        fh.setLevel(logging.WARNING)  # Only warnings and errors to file
        logger.addHandler(fh)
        # Also ensure the logger itself isn't filtered
        if logger.level == logging.NOTSET or logger.level > logging.DEBUG:
            logger.setLevel(logging.DEBUG)
        _file_handler_attached = True
    except Exception:
        pass  # Don't crash on logging setup failure


def _load_env():
    """Load .env files to get GEMINI_API_KEY."""
    for env_path in [SUITE_ROOT / ".env", WORKSPACE_ROOT / ".env"]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                val = val.strip().strip("'\"")
                os.environ.setdefault(key.strip(), val)


def get_model_name() -> str:
    """Read Gemini model name from config.json."""
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return config.get("gemini", {}).get("model", "gemini-3-pro-preview")
    except Exception:
        return "gemini-3-pro-preview"


def _get_client():
    """Initialize Gemini client (lazy, cached)."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    _ensure_file_logging()
    _load_env()

    try:
        from google import genai
    except ImportError as e:
        msg = "google-genai not installed. Run: pip install google-genai>=1.51.0"
        logger.error(msg)
        raise ImportError(msg) from e

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        msg = (
            "GEMINI_API_KEY not set. Checked os.environ and .env files at:\n"
            f"  - {SUITE_ROOT / '.env'}\n"
            f"  - {WORKSPACE_ROOT / '.env'}"
        )
        logger.error(msg)
        raise EnvironmentError(msg)

    _gemini_client = genai.Client(api_key=api_key)
    logger.info("Gemini client initialized (model: %s)", get_model_name())
    return _gemini_client


def call_gemini(prompt: str, max_retries: int = 3, temperature: float = 1.0) -> str:
    """Call Gemini with retries, rate limiting, and detailed error logging.

    Returns the response text. Raises on all retries exhausted.
    """
    global _last_call_time

    client = _get_client()
    model = get_model_name()

    # Rate limit: enforce minimum interval between calls
    elapsed = time.time() - _last_call_time
    if elapsed < MIN_CALL_INTERVAL:
        wait_for = MIN_CALL_INTERVAL - elapsed
        logger.debug("Rate limit: waiting %.1fs before API call", wait_for)
        time.sleep(wait_for)

    last_error = None
    for attempt in range(max_retries):
        try:
            _last_call_time = time.time()
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": temperature},
            )
            return response.text
        except Exception as e:
            last_error = e
            err_str = str(e).lower()

            # Classify the error
            if "rate" in err_str or "quota" in err_str or "429" in err_str or "resource" in err_str:
                wait = 30 * (attempt + 1)
                logger.warning(
                    "Gemini rate limit (attempt %d/%d, model=%s): %s. Waiting %ds...",
                    attempt + 1, max_retries, model, e, wait,
                )
            elif "not found" in err_str or "404" in err_str:
                # Model doesn't exist — no point retrying
                logger.error(
                    "Gemini model not found (model=%s): %s. "
                    "Check gemini.model in config.json. Available models: "
                    "gemini-2.0-flash, gemini-2.5-flash-preview, gemini-3-pro-preview",
                    model, e,
                )
                raise
            elif "api_key" in err_str or "401" in err_str or "403" in err_str or "permission" in err_str:
                logger.error(
                    "Gemini auth error: %s. Check GEMINI_API_KEY in .env", e,
                )
                raise
            elif "safety" in err_str or "blocked" in err_str:
                logger.warning(
                    "Gemini safety filter blocked response (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                wait = 2
            else:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "Gemini API error (attempt %d/%d, model=%s): %s. Retrying in %ds...",
                    attempt + 1, max_retries, model, e, wait,
                )
            time.sleep(wait)

    logger.error(
        "Gemini call failed after %d attempts (model=%s). Last error: %s",
        max_retries, model, last_error,
    )
    raise last_error
