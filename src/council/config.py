"""
council/config.py

Centralised configuration loader.
All modules should import from here rather than calling load_dotenv themselves.
Uses an explicit path to the .env file anchored to the project root,
so it works regardless of the working directory at invocation time.
"""

from __future__ import annotations

import builtins
import io
import locale
import os
import sys
from pathlib import Path

# ── Force UTF-8 encoding on Windows ──────────────────────────────────────
# Both main.py (CLI) and server.py (GUI) import config.py first, so this
# runs before any YAML reading, file I/O, or third-party library internals.
# On Chinese/Japanese/Korean Windows, the system ANSI code page (GBK etc.)
# is the default for ALL I/O, causing crashes on Unicode characters in
# LLM output: "'gbk' codec can't decode byte 0x94: illegal multibyte sequence"

_original_open = builtins.open

def _utf8_open(file, mode="r", buffering=-1, encoding=None, errors=None,
               newline=None, closefd=True, opener=None):
    if encoding is None and ("r" in mode or "w" in mode or "a" in mode or "x" in mode):
        if "b" not in mode:
            encoding = "utf-8"
            errors = errors or "replace"
    return _original_open(file, mode, buffering, encoding, errors,
                          newline, closefd, opener)

if sys.platform == "win32":
    builtins.open = _utf8_open
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "buffer"):
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    try:
        locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
    except locale.Error:
        pass

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from dotenv import load_dotenv

# Project root is 3 levels up from this file: src/council/config.py → src/council → src → root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=_ENV_FILE, override=True)


def get_deepseek_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key or key.startswith("sk-xxxxx"):
        raise EnvironmentError(
            f"DEEPSEEK_API_KEY is not set or is still a placeholder.\n"
            f"Edit: {_ENV_FILE}"
        )
    return key


def get_gemini_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key.startswith("AIzaSyXXX"):
        raise EnvironmentError(
            f"GEMINI_API_KEY is not set or is still a placeholder.\n"
            f"Edit: {_ENV_FILE}"
        )
    return key


def get_tavily_key() -> str | None:
    """Returns Tavily key, or None if not set (triggers DuckDuckGo fallback)."""
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key or key.startswith("tvly-xxxxx"):
        return None
    return key


def get_provider() -> str:
    return os.getenv("AI_PROVIDER", "ds").strip().lower()


def build_llm(temperature: float = 0.7) -> object:
    """
    Build a crewAI-compatible LLM based on AI_PROVIDER env var.
    Centralised so all agents use the same configuration.
    """
    from crewai import LLM

    provider = get_provider()
    if provider == "ds":
        model = os.getenv("MODEL", "deepseek/deepseek-chat")
        return LLM(
            model=model,
            api_key=get_deepseek_key(),
            temperature=temperature,
            timeout=120,
        )
    else:
        return LLM(
            model=os.getenv("MODEL", "gemini/gemini-2.5-flash-lite"),
            api_key=get_gemini_key(),
            temperature=temperature,
            timeout=120,
        )
