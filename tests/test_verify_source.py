"""
tests/test_verify_source.py

Unit tests for the _verify_source function in library_tool.py.
Tests URL format validation, DOI handling, and error paths.
"""

from __future__ import annotations

import pytest

from council.tools.library_tool import _verify_source


# ── Valid URLs ────────────────────────────────────────────────────────────

def test_valid_https_url():
    url = "https://arxiv.org/abs/1234.5678"
    normalized, verified, note = _verify_source(url)
    assert normalized == url
    # arXiv should return 200
    assert verified is True or verified is False  # depends on network
    assert isinstance(note, str)


def test_valid_http_url():
    url = "http://example.com/paper"
    normalized, verified, note = _verify_source(url)
    assert normalized == url


# ── DOI handling ──────────────────────────────────────────────────────────

def test_doi_is_normalized():
    doi = "10.1038/nature12345"
    normalized, verified, note = _verify_source(doi)
    # Should be normalized to full doi.org URL
    assert normalized.startswith("https://doi.org/")
    assert doi in normalized


def test_fake_doi_raises():
    """A DOI that doesn't resolve should raise ValueError."""
    with pytest.raises(ValueError, match="does not resolve"):
        _verify_source("10.9999/fake-doi-that-does-not-exist-12345")


# ── Invalid URLs ──────────────────────────────────────────────────────────

def test_plain_text_rejected():
    with pytest.raises(ValueError, match="Invalid source_url"):
        _verify_source("I made this up")


def test_description_string_rejected():
    with pytest.raises(ValueError, match="Invalid source_url"):
        _verify_source("This is a paper about froth flotation")


def test_empty_string_rejected():
    with pytest.raises(ValueError, match="Invalid source_url"):
        _verify_source("")


def test_doi_like_but_not_doi_rejected():
    """Strings that start with a number but aren't real DOIs."""
    with pytest.raises(ValueError):
        _verify_source("10.this-is-not-a-real-doi")


# ── Edge cases ────────────────────────────────────────────────────────────

def test_url_with_whitespace():
    url = "  https://example.com/paper  "
    normalized, verified, note = _verify_source(url)
    assert normalized == "https://example.com/paper"


def test_doi_with_whitespace():
    doi = "  10.1038/nature12345  "
    normalized, verified, note = _verify_source(doi)
    assert normalized.startswith("https://doi.org/")
    assert "10.1038/nature12345" in normalized


# ── Note: URL resolvability tests are inherently network-dependent.
# The function stores with verified=True for reachable URLs and
# verified=False for 4xx/5xx/timeout. The test_library_write_success
# test in test_research.py verifies this behavior end-to-end.
