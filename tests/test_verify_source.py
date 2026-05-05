"""
tests/test_verify_source.py

Unit tests for the quote-based _verify_source function.
The new verifier NEVER raises — it always returns (url, status, note).
"""

from __future__ import annotations

from council.tools.library_tool import _verify_source, VERIFIED, MISATTRIBUTED, UNVERIFIABLE


def test_doi_verified():
    doi = "10.1038/nature12345"
    url, status, note = _verify_source(doi)
    assert status == VERIFIED
    assert url.startswith("https://doi.org/")


def test_valid_url_with_quote_found():
    """A real URL with a quote that can be found — should verify or misattribute."""
    url, status, note = _verify_source(
        "https://arxiv.org/abs/1234.5678",
        "generative adversarial networks"
    )
    # May be verified or misattributed depending on where the quote is found
    assert status in (VERIFIED, MISATTRIBUTED)


def test_no_longer_raises():
    """The new _verify_source never raises ValueError."""
    url, status, note = _verify_source("not a url at all")
    assert status == UNVERIFIABLE


def test_empty_string_returns_unverifiable():
    url, status, note = _verify_source("")
    assert status == UNVERIFIABLE


def test_fake_url_with_quote():
    """A fake URL should be corrected if the quote is found elsewhere."""
    url, status, note = _verify_source(
        "https://totally-fake-paper-that-does-not-exist.com",
        "generative adversarial networks"
    )
    # Should be misattributed (correction) or unverifiable (quote not found)
    assert status in (MISATTRIBUTED, UNVERIFIABLE)


def test_fake_url_no_quote():
    """A fake URL without a quote — unverifiable."""
    url, status, note = _verify_source("https://totally-fake-12345.com")
    assert status == UNVERIFIABLE


def test_doi_normalization():
    doi = "10.1038/nature12345"
    url, status, note = _verify_source(doi)
    assert url.startswith("https://doi.org/")


def test_status_values():
    """Verify the three status constants are distinct strings."""
    assert VERIFIED != MISATTRIBUTED
    assert MISATTRIBUTED != UNVERIFIABLE
    assert VERIFIED != UNVERIFIABLE
