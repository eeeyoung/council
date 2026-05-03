"""
council/config.py

Centralised configuration loader.
All modules should import from here rather than calling load_dotenv themselves.
Uses an explicit path to the .env file anchored to the project root,
so it works regardless of the working directory at invocation time.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root is 3 levels up from this file: src/council/config.py → src/council → src → root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

# Load once at import time; override=True ensures values in .env win over
# any stale shell environment variables.
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
        return LLM(
            model="deepseek/deepseek-chat",
            api_key=get_deepseek_key(),
            temperature=temperature,
        )
    else:
        return LLM(
            model=os.getenv("MODEL", "gemini/gemini-2.5-flash-lite"),
            api_key=get_gemini_key(),
            temperature=temperature,
        )
