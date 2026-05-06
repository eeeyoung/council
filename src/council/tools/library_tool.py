"""
council/tools/library_tool.py

Shared Research Library — ChromaDB-backed vector store shared across ALL agents
in a COUNCIL session.

Design:
- One persistent ChromaDB collection per session_id
- Agents WRITE findings with LibraryWriteTool (quote-based source verification)
- Agents READ (semantic search) with LibraryReadTool
- Source verification uses quote text + web search, not HEAD requests
- The tool NEVER rejects — it auto-corrects or stores with rich metadata
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.error
import urllib.request
from typing import Type

import chromadb
from chromadb.config import Settings
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

import council.config  # noqa: F401
from council.state import SourcePoolEntry

# ------------------------------------------------------------------ #
# Singleton ChromaDB client + collection registry
# ------------------------------------------------------------------ #

_clients: dict[str, chromadb.ClientAPI] = {}
_collections: dict[str, chromadb.Collection] = {}

_DOI_PATTERN = re.compile(r"^10\.\d{4,}/[^\s]+$")


def _get_collection(session_id: str) -> chromadb.Collection:
    if session_id not in _clients:
        db_path = os.path.join(os.getcwd(), "chroma_db", session_id)
        os.makedirs(db_path, exist_ok=True)
        _clients[session_id] = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )
    client = _clients[session_id]
    collection_name = f"council_{session_id}"
    if session_id not in _collections:
        # Use the default Sentence Transformers embedding (all-MiniLM-L6-v2),
        # which works offline. Explicitly set to avoid auto-detecting Google
        # embeddings from environment variables.
        from chromadb.utils import embedding_functions
        ef = embedding_functions.DefaultEmbeddingFunction()
        _collections[session_id] = client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collections[session_id]


def reset_library(session_id: str) -> None:
    _clients.pop(session_id, None)
    _collections.pop(session_id, None)


# ------------------------------------------------------------------ #
# Source verification — quote-based, never reject
# ------------------------------------------------------------------ #

# Verification status values
VERIFIED = "verified"
MISATTRIBUTED = "misattributed"
UNVERIFIABLE = "unverifiable"


def _search_quote_on_web(quote: str) -> str | None:
    """Search the web for a quote and return the URL where it was found, or None."""
    # Try DuckDuckGo first (no API key needed)
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            for r in ddgs.text(quote[:200], max_results=3):
                body = r.get("body", "")
                href = r.get("href", "")
                # Check if any significant part of the quote appears in the result
                check = quote[:80].strip()
                if check.lower() in body.lower() and href:
                    return href
    except Exception:
        pass

    # Try Tavily if available
    try:
        import council.config as cfg

        key = cfg.get_tavily_key()
        if key:
            from tavily import TavilyClient

            client = TavilyClient(api_key=key)
            resp = client.search(query=quote[:200], max_results=3, search_depth="advanced")
            for r in resp.get("results", []):
                content = r.get("content", "")
                url = r.get("url", "")
                check = quote[:80].strip()
                if check.lower() in content.lower() and url:
                    return url
    except Exception:
        pass

    return None


def _verify_source(
    source_url: str,
    source_quote: str = "",
) -> tuple[str, str, str]:
    """
    Verify a source using quote text and web search.
    Never raises — always returns (normalized_url, status, note).

    status is one of: "verified", "misattributed", "unverifiable"
    """
    raw_url = source_url.strip() if source_url else ""
    raw_quote = source_quote.strip() if source_quote else ""

    # ── DOI ──────────────────────────────────────────────────────────
    doi_match = _DOI_PATTERN.match(raw_url)
    if doi_match:
        doi = raw_url
        try:
            req = urllib.request.Request(
                f"https://doi.org/api/handles/{doi}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return f"https://doi.org/{doi}", VERIFIED, "DOI verified via doi.org"
        except Exception:
            pass
        # DOI didn't resolve
        if raw_quote:
            found_url = _search_quote_on_web(raw_quote)
            if found_url:
                return found_url, MISATTRIBUTED, (
                    f"DOI {doi} did not resolve, but source quote was found at {found_url}. "
                    f"URL auto-corrected."
                )
        return raw_url, UNVERIFIABLE, f"DOI {doi} does not resolve"

    # ── No URL provided — try quote search ───────────────────────────
    if not raw_url:
        if raw_quote:
            found_url = _search_quote_on_web(raw_quote)
            if found_url:
                return found_url, VERIFIED, f"Source quote found at {found_url}. URL auto-discovered."
            return "", UNVERIFIABLE, "Source quote not found on the web — it may be fabricated"
        return "", UNVERIFIABLE, "No URL or source quote provided"

    # ── URL format check ─────────────────────────────────────────────
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        if raw_quote:
            found_url = _search_quote_on_web(raw_quote)
            if found_url:
                return found_url, MISATTRIBUTED, (
                    f"'{raw_url}' is not a valid URL. Source quote found at {found_url}. "
                    f"URL auto-corrected."
                )
        return raw_url, UNVERIFIABLE, f"'{raw_url}' is not a valid URL"

    # ── Quote verification ───────────────────────────────────────────
    if raw_quote:
        found_url = _search_quote_on_web(raw_quote)
        if found_url:
            # Check if the found URL matches the claimed URL
            claimed_domain = _extract_domain(raw_url)
            found_domain = _extract_domain(found_url)
            if claimed_domain and found_domain and claimed_domain == found_domain:
                return raw_url, VERIFIED, f"Source quote confirmed on {found_domain}"
            else:
                return found_url, MISATTRIBUTED, (
                    f"Source quote found on a different source ({found_url}) "
                    f"than claimed ({raw_url}). URL auto-corrected."
                )
        else:
            return raw_url, UNVERIFIABLE, "Source quote not found on the web — it may be fabricated"
    else:
        # No quote — basic URL reachability check
        try:
            req = urllib.request.Request(raw_url, method="HEAD")
            req.add_header("User-Agent", "COUNCIL/0.1")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return raw_url, VERIFIED, f"URL reachable (HTTP {resp.status})"
        except urllib.error.HTTPError as e:
            return raw_url, UNVERIFIABLE, (
                f"URL returned HTTP {e.code} — cannot verify without source quote"
            )
        except Exception:
            return raw_url, UNVERIFIABLE, (
                "URL unreachable and no source quote provided — cannot verify"
            )


def _extract_domain(url: str) -> str:
    """Extract the domain from a URL for comparison."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return ""


# ------------------------------------------------------------------ #
# Tool input schemas
# ------------------------------------------------------------------ #


class LibraryWriteInput(BaseModel):
    session_id: str = Field(..., description="The current COUNCIL session ID.")
    content: str = Field(
        ...,
        description="The text content to store (a finding, quote, or summary).",
    )
    source_url: str = Field(
        default="",
        description="The URL or DOI from your web search results.",
    )
    source_quote: str = Field(
        default="",
        description="REQUIRED: The exact sentence(s) from the source that support this finding. Copy-paste from the search result snippet or the source text.",
    )
    agent_name: str = Field(..., description="Your expert name.")
    search_reference: str = Field(
        default="",
        description="Optional: which search result this came from (e.g. 'from search result #2').",
    )


class LibraryReadInput(BaseModel):
    session_id: str = Field(..., description="The current COUNCIL session ID.")
    query: str = Field(
        ...,
        description="A natural language query to semantically search the shared library.",
    )
    n_results: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of results to return.",
    )


# ------------------------------------------------------------------ #
# Tools
# ------------------------------------------------------------------ #


class LibraryWriteTool(BaseTool):
    """
    Store a research finding in the shared COUNCIL library.
    The source is verified using quote-based web search — not unreliable HEAD requests.
    The tool NEVER rejects — it auto-corrects URLs or stores with rich metadata.
    """

    name: str = "library_write"
    description: str = (
        "Save a research finding to the shared COUNCIL library. "
        "Provide: session_id, content (key finding/quote), source_url (exact URL "
        "from search results), source_quote (the EXACT sentence from the source "
        "that supports this finding — copy-paste it), and agent_name. "
        "The system will verify the quote and auto-correct the URL if needed."
    )
    args_schema: Type[BaseModel] = LibraryWriteInput

    def _run(
        self,
        session_id: str,
        content: str,
        agent_name: str,
        source_url: str = "",
        source_quote: str = "",
        search_reference: str = "",
    ) -> str:
        # ── Verify (never reject) ─────────────────────────────────────
        normalized_url, status, note = _verify_source(source_url, source_quote)
        if not normalized_url and status == UNVERIFIABLE:
            normalized_url = "UNCITED"

        # ── Store ────────────────────────────────────────────────────
        try:
            collection = _get_collection(session_id)

            doc_id = hashlib.md5(
                f"{agent_name}:{normalized_url}:{content[:100]}".encode()
            ).hexdigest()

            metadata = {
                "source_url": normalized_url,
                "agent_name": agent_name,
                "verification_status": status,
                "verification_note": note,
                "source_quote": source_quote,
            }
            if search_reference:
                metadata["search_reference"] = search_reference

            collection.add(
                documents=[content],
                metadatas=[metadata],
                ids=[doc_id],
            )

            parts = []
            if status == VERIFIED:
                parts.append(f"✓ VERIFIED — Finding stored (id={doc_id[:8]})")
                parts.append(f"  Source: {normalized_url}")
                parts.append(f"  Note: {note}")
            elif status == MISATTRIBUTED:
                parts.append(f"⚠ MISATTRIBUTED — Finding stored with auto-corrected URL (id={doc_id[:8]})")
                parts.append(f"  Your URL: {source_url}")
                parts.append(f"  Corrected: {normalized_url}")
                parts.append(f"  Note: {note}")
            else:
                parts.append(f"⚠ UNVERIFIABLE — Finding stored but source could not be verified (id={doc_id[:8]})")
                parts.append(f"  Source: {normalized_url}")
                parts.append(f"  Note: {note}")
                parts.append(f"  TIP: Ensure source_quote is an EXACT sentence from the source. Rephrasing prevents verification.")

            if search_reference:
                parts.append(f"  Trace: {search_reference}")
            return "\n".join(parts)

        except Exception as exc:
            return f"Library write failed: {exc}"


class LibraryReadTool(BaseTool):
    """
    Search the shared COUNCIL library for relevant evidence.
    """

    name: str = "library_read"
    description: str = (
        "Semantically search the shared COUNCIL research library for evidence "
        "relevant to your query. Returns matching findings with source URLs, "
        "verification status, source quotes, and contributor info."
    )
    args_schema: Type[BaseModel] = LibraryReadInput

    def _run(self, session_id: str, query: str, n_results: int = 5) -> str:
        try:
            collection = _get_collection(session_id)
            count = collection.count()
            if count == 0:
                return "The shared library is currently empty."

            actual_n = min(n_results, count)
            results = collection.query(query_texts=[query], n_results=actual_n)

            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            if not documents:
                return f"No relevant findings for: '{query}'"

            lines: list[str] = [f"Library search results for: '{query}'\n"]
            for i, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances), 1):
                relevance = round((1 - dist) * 100, 1)
                agent = meta.get("agent_name", "Unknown")
                url = meta.get("source_url", "No URL")
                status = meta.get("verification_status", UNVERIFIABLE)
                status_str = {"verified": "✓ verified", "misattributed": "⚠ misattributed", "unverifiable": "⚠ unverifiable"}.get(status, status)
                quote = meta.get("source_quote", "")
                note = meta.get("verification_note", "")
                search_ref = meta.get("search_reference", "")
                snippet = doc[:300] + "…" if len(doc) > 300 else doc
                lines.append(f"[{i}] Relevance: {relevance}%  |  Contributed by: {agent}")
                lines.append(f"    Status: {status_str}")
                lines.append(f"    Source: {url}")
                if quote:
                    lines.append(f"    Quote: \"{quote[:200]}\"")
                if note:
                    lines.append(f"    Note: {note}")
                if search_ref:
                    lines.append(f"    Trace: {search_ref}")
                lines.append(f"    {snippet}")
                lines.append("")

            return "\n".join(lines)

        except Exception as exc:
            return f"Library read failed: {exc}"


# ------------------------------------------------------------------ #
# Source Pool — Phase B1 collection (pre-verification)
# ------------------------------------------------------------------ #

# In-memory source pool keyed by session_id
_source_pools: dict[str, list] = {}


class SourcePoolWriteInput(BaseModel):
    session_id: str = Field(..., description="The current COUNCIL session ID.")
    url: str = Field(..., description="The URL from your search result.")
    title: str = Field(default="", description="The title of the source.")
    snippet: str = Field(default="", description="The search result snippet or excerpt.")
    agent_name: str = Field(..., description="Your expert name.")


class SourcePoolWriteTool(BaseTool):
    """
    Deposit a candidate source into the Source Pool during Phase B1 (Collection).
    Do NOT make claims or opinions — just record the source you found.
    The Fact-Checker will verify all pool entries before analysis begins.
    """

    name: str = "source_pool_write"
    description: str = (
        "Deposit a source you found via web search into the Source Pool. "
        "Provide: session_id, url (exact URL from search result), title, "
        "snippet (the text excerpt from the search result), and agent_name. "
        "Do NOT make claims or opinions — just record what you found. "
        "The Fact-Checker will verify all sources before you can use them."
    )
    args_schema: Type[BaseModel] = SourcePoolWriteInput

    def _run(self, session_id: str, url: str, title: str = "",
             snippet: str = "", agent_name: str = "") -> str:
        if session_id not in _source_pools:
            _source_pools[session_id] = []
        pool = _source_pools[session_id]
        # Deduplicate by URL + agent
        for entry in pool:
            if entry.url == url and entry.agent_name == agent_name:
                return f"⚠ Source already in pool: {url}"
        pool.append(SourcePoolEntry(
            url=url, title=title, snippet=snippet, agent_name=agent_name,
        ))
        return f"✓ Source deposited in pool ({len(pool)} total): {title or url}"


class SourcePoolReadInput(BaseModel):
    session_id: str = Field(..., description="The current COUNCIL session ID.")


class SourcePoolReadTool(BaseTool):
    """Read all sources currently in the Source Pool."""

    name: str = "source_pool_read"
    description: str = "List all sources currently in the Source Pool with their verification status."
    args_schema: Type[BaseModel] = SourcePoolReadInput

    def _run(self, session_id: str) -> str:
        pool = _source_pools.get(session_id, [])
        if not pool:
            return "The Source Pool is empty."
        lines = [f"Source Pool ({len(pool)} entries):\n"]
        for i, e in enumerate(pool, 1):
            status = e.status or "pending"
            lines.append(f"[{i}] [{status}] {e.title or e.url}")
            lines.append(f"    URL: {e.url}")
            lines.append(f"    From: {e.agent_name}")
            lines.append("")
        return "\n".join(lines)


def get_source_pool(session_id: str) -> list[SourcePoolEntry]:
    """Get the source pool for a session (for gate check)."""
    return _source_pools.get(session_id, [])


def clear_source_pool(session_id: str) -> None:
    """Clear the source pool after gate check."""
    _source_pools.pop(session_id, None)


def create_library_tools() -> tuple[LibraryWriteTool, LibraryReadTool]:
    return LibraryWriteTool(), LibraryReadTool()


def create_source_pool_tools() -> tuple[SourcePoolWriteTool, SourcePoolReadTool]:
    return SourcePoolWriteTool(), SourcePoolReadTool()
