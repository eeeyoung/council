"""
tests/test_config.py

Tests for central configuration: LLM building, API key validation, provider selection.
"""

from __future__ import annotations

import os

import pytest

import council.config as config_module


# ── get_provider ──────────────────────────────────────────────────────────

def test_get_provider_default():
    """Default provider is 'ds' when AI_PROVIDER is unset."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert config_module.get_provider() == "ds"
    monkeypatch.undo()


def test_get_provider_deepseek():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("AI_PROVIDER", "ds")
    assert config_module.get_provider() == "ds"
    monkeypatch.undo()


def test_get_provider_gemini():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("AI_PROVIDER", "gem")
    assert config_module.get_provider() == "gem"
    monkeypatch.undo()


# ── get_tavily_key ────────────────────────────────────────────────────────

def test_tavily_key_missing():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert config_module.get_tavily_key() is None
    monkeypatch.undo()


def test_tavily_key_placeholder():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-xxxxx")
    assert config_module.get_tavily_key() is None
    monkeypatch.undo()


def test_tavily_key_valid():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-real-key-123")
    assert config_module.get_tavily_key() == "tvly-real-key-123"
    monkeypatch.undo()


# ── API key validation ────────────────────────────────────────────────────

def test_deepseek_key_placeholder_raises():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-xxxxx")
    with pytest.raises(EnvironmentError, match="DEEPSEEK_API_KEY"):
        config_module.get_deepseek_key()
    monkeypatch.undo()


def test_deepseek_key_missing_raises():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="DEEPSEEK_API_KEY"):
        config_module.get_deepseek_key()
    monkeypatch.undo()


def test_gemini_key_placeholder_raises():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyXXX")
    with pytest.raises(EnvironmentError, match="GEMINI_API_KEY"):
        config_module.get_gemini_key()
    monkeypatch.undo()


def test_gemini_key_missing_raises():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="GEMINI_API_KEY"):
        config_module.get_gemini_key()
    monkeypatch.undo()


def test_deepseek_key_valid():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real-deepseek-key-123456")
    monkeypatch.setenv("AI_PROVIDER", "ds")
    assert config_module.get_deepseek_key() == "sk-real-deepseek-key-123456"
    monkeypatch.undo()


def test_gemini_key_valid():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyRealKey123")
    monkeypatch.setenv("AI_PROVIDER", "gem")
    assert config_module.get_gemini_key() == "AIzaSyRealKey123"
    monkeypatch.undo()


# ── build_llm ─────────────────────────────────────────────────────────────

def test_build_llm_deepseek():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("AI_PROVIDER", "ds")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real-key-123456")
    # build_llm should construct without error
    llm = config_module.build_llm(temperature=0.5)
    assert llm is not None
    assert llm.temperature == 0.5
    monkeypatch.undo()


def test_build_llm_gemini():
    pytest.importorskip("google.genai", reason="google-genai package not installed")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("AI_PROVIDER", "gem")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyRealKey123")
    llm = config_module.build_llm(temperature=0.3)
    assert llm is not None
    assert llm.temperature == 0.3
    monkeypatch.undo()
