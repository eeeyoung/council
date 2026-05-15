"""
Smoke-test harness for evaluating trafilatura extraction quality against a
given URL.  Saves extracted content to disk in multiple formats so a human
can judge whether the Fact-Checker would have enough material to verify
a claim against the page.

Usage:
    uv run python tests/test_trafilatura_extraction.py <url>
    uv run python tests/test_trafilatura_extraction.py <url> -o my_output
"""

from __future__ import annotations

import argparse
import json as _json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import trafilatura
from trafilatura import extract
from trafilatura.metadata import extract_metadata

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

OUTPUT_FORMATS = ("txt", "markdown", "html", "json")


def _slugify(url: str) -> str:
    """Derive a directory-safe name from a URL."""
    # Grab the last path segment that looks meaningful
    parts = [p for p in url.rstrip("/").split("/") if p]
    # Try to find an article ID or DOI-like segment
    for p in reversed(parts):
        # e.g. "s41467-026-72292-0" or "10.1371_journal.pone.0301234"
        if re.search(r"\d", p) and len(p) > 4:
            return re.sub(r"[^a-zA-Z0-9._-]", "_", p)
    # Fallback: last segment
    last = parts[-1] if parts else "page"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", last)


def fetch_page(url: str) -> tuple[str, str] | None:
    """Return (html_string, final_url) or None on failure."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            return html, resp.geturl()
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.reason}")
        body = e.read().decode("utf-8", errors="replace")
        print(f"Error body preview: {body[:300]}")
        return None
    except Exception as e:
        print(f"Fetch failed: {type(e).__name__}: {e}")
        return None


def extract_safe(html_str: str, fmt: str, with_meta: bool = False) -> str | None:
    """Extract, falling back to no-metadata on crash (trafilatura bug workaround)."""
    try:
        return extract(html_str, output_format=fmt, with_metadata=with_meta)
    except Exception:
        if with_meta:
            print(f"  (metadata extraction failed for {fmt} — retrying without)")
            return extract(html_str, output_format=fmt, with_metadata=False)
        return None


def save_all(url: str, output_dir: str) -> None:
    """Fetch a URL, save raw HTML + all extraction formats + metadata to disk."""
    slug = _slugify(url)
    out = Path(output_dir) / slug
    os.makedirs(out, exist_ok=True)

    print(f"URL: {url}")
    print(f"Output: {out}/\n")

    # ── Fetch ───────────────────────────────────────────────────────────
    result = fetch_page(url)
    if result is None:
        print("FAILED: could not fetch page.\n")
        return

    html_str, final_url = result
    if final_url != url:
        print(f"Redirected to: {final_url}")

    print(f"HTML size: {len(html_str):,} bytes")

    # Save raw HTML
    raw_path = out / "raw.html"
    raw_path.write_text(html_str, encoding="utf-8")
    print(f"  ✓ raw.html ({len(html_str):,} bytes)")

    # ── Metadata ────────────────────────────────────────────────────────
    meta = extract_metadata(html_str)
    meta_dict: dict = {}
    if meta:
        meta_dict = meta.as_dict()
        # Convert any non-serializable values
        for k, v in meta_dict.items():
            if not isinstance(v, (str, int, float, bool, list, dict, type(None))):
                meta_dict[k] = str(v)
        meta_path = out / "metadata.json"
        meta_path.write_text(_json.dumps(meta_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  ✓ metadata.json")
        for key in ("title", "author", "date", "sitename", "categories", "license"):
            val = meta_dict.get(key)
            if val:
                print(f"      {key}: {val}")

    # ── Extract all formats ─────────────────────────────────────────────
    total_chars: dict[str, int] = {}
    for fmt in OUTPUT_FORMATS:
        with_meta = (fmt == "markdown")
        content = extract_safe(html_str, fmt, with_meta=with_meta)
        if content is None:
            print(f"  ✗ {fmt} — extraction returned None")
            continue
        ext = "md" if fmt == "markdown" else fmt
        fpath = out / f"extracted.{ext}"
        fpath.write_text(content, encoding="utf-8")
        total_chars[fmt] = len(content)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\nExtraction summary:")
    for fmt, chars in total_chars.items():
        ext = "md" if fmt == "markdown" else fmt
        verdict = (
            "RICH — full article body"
            if chars > 5000
            else "THIN — likely paywalled"
        )
        print(f"  {ext:>8}: {chars:>8,} chars  →  {verdict}")

    print(f"\nAll files saved to: {out.resolve()}/\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract content from a URL using trafilatura and save to disk."
    )
    parser.add_argument("url", help="The URL to fetch and extract")
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Parent output directory (default: output/)",
    )
    args = parser.parse_args()
    save_all(args.url, args.output_dir)


if __name__ == "__main__":
    main()
