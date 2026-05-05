"""
council/tools/library_tool.py

Shared Research Library — ChromaDB-backed vector store shared across ALL agents
in a COUNCIL session.

Design:
- One persistent ChromaDB collection per session_id (created on first access)
- Agents WRITE findings with LibraryWriteTool (with inline source verification)
- Agents READ (semantic search) with LibraryReadTool
- The singleton pattern ensures all agents in the same process share the same store

Both tools are exposed as crewAI BaseTool instances.
"""

from __future__ import annotations

import hashlib
import json
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

# ------------------------------------------------------------------ #
# Singleton ChromaDB client + collection registry
# ------------------------------------------------------------------ #

_clients: dict[str, chromadb.ClientAPI] = {}
_collections: dict[str, chromadb.Collection] = {}

# DOI pattern: 10.XXXX/... (e.g. 10.1038/nature12345)
_DOI_PATTERN = re.compile(r"^10\.\d{4,}/[^\s]+$")


def _get_collection(session_id: str) -> chromadb.Collection:
    """Return (or create) the ChromaDB collection for this session."""
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
        _collections[session_id] = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    return _collections[session_id]


def reset_library(session_id: str) -> None:
    """Clear the library for a session (used in tests)."""
    _clients.pop(session_id, None)
    _collections.pop(session_id, None)


# ------------------------------------------------------------------ #
# Source verification
# ------------------------------------------------------------------ #


def _verify_source(source_url: str) -> tuple[str, bool, str]:
    """
    Validate and verify a source URL or DOI before storing.

    Returns (normalized_url, verified, note).
    Raises ValueError for invalid formats or unresolvable DOIs.
    """
    raw = source_url.strip()

    # ── DOI ──────────────────────────────────────────────────────────
    doi_match = _DOI_PATTERN.match(raw)
    if doi_match:
        doi = raw
        try:
            req = urllib.request.Request(
                f"https://doi.org/api/handles/{doi}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return f"https://doi.org/{doi}", True, "DOI verified via doi.org"
        except Exception:
            raise ValueError(
                f"DOI '{doi}' does not resolve. It may be fabricated or mistyped. "
                f"Please use the exact DOI from your web search results."
            )
        return f"https://doi.org/{doi}", True, "DOI verified via doi.org"

    # ── URL format check ─────────────────────────────────────────────
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raise ValueError(
            f"Invalid source_url: '{raw}'. "
            f"The source_url must be a real URL (starting with http:// or https://) "
            f"or a DOI (e.g. 10.1234/example) from your web search results. "
            f"Do not make up descriptions or placeholder strings."
        )

    # ── URL resolvability check ──────────────────────────────────────
    try:
        req = urllib.request.Request(raw, method="HEAD")
        req.add_header("User-Agent", "COUNCIL/0.1 Source Verification")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return raw, True, f"URL reachable (HTTP {resp.status})"
    except urllib.error.HTTPError as e:
        # 4xx/5xx — store with warning (many academic sites return 403 for HEAD)
        return raw, False, f"URL returned HTTP {e.code} (may be paywalled or restricted)"
    except Exception:
        return raw, False, "URL unreachable (timeout or connection error)"


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
        ...,
        description="The URL or DOI from your web search results. Must be a real URL, not made up.",
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

    IMPORTANT: The source_url is verified before storage. Fabricated or invalid
    URLs/DOIs will be rejected. Only real sources from your web search results
    will be accepted.
    """

    name: str = "library_write"
    description: str = (
        "Save a research finding to the shared COUNCIL library. "
        "Provide: the session_id, the content (a key finding or quote), "
        "the source_url (the EXACT URL or DOI from your web search results — "
        "do NOT make up or guess URLs), your agent_name, and optionally "
        "a search_reference noting which search result this came from. "
        "The source will be verified before storage."
    )
    args_schema: Type[BaseModel] = LibraryWriteInput

    def _run(
        self,
        session_id: str,
        content: str,
        source_url: str,
        agent_name: str,
        search_reference: str = "",
    ) -> str:
        # ── Verify the source ────────────────────────────────────────
        try:
            normalized_url, verified, note = _verify_source(source_url)
        except ValueError as exc:
            return f"❌ REJECTED: {exc}"

        # ── Store ────────────────────────────────────────────────────
        try:
            collection = _get_collection(session_id)

            doc_id = hashlib.md5(
                f"{agent_name}:{normalized_url}:{content[:100]}".encode()
            ).hexdigest()

            metadata = {
                "source_url": normalized_url,
                "agent_name": agent_name,
                "verified": verified,
                "verification_note": note,
            }
            if search_reference:
                metadata["search_reference"] = search_reference

            collection.add(
                documents=[content],
                metadatas=[metadata],
                ids=[doc_id],
            )

            status = "✓ VERIFIED" if verified else "⚠ STORED (unverified)"
            parts = [f"{status} — Finding stored in library (id={doc_id[:8]})"]
            parts.append(f"  Source: {normalized_url}")
            if note:
                parts.append(f"  Note: {note}")
            if search_reference:
                parts.append(f"  Trace: {search_reference}")
            return "\n".join(parts)

        except Exception as exc:
            return f"Library write failed: {exc}"


class LibraryReadTool(BaseTool):
    """
    Search the shared COUNCIL library for relevant evidence.
    Use this to find evidence supporting or contradicting claims in the debate.
    """

    name: str = "library_read"
    description: str = (
        "Semantically search the shared COUNCIL research library for evidence "
        "relevant to your query. Returns matching findings with their source URLs, "
        "verification status, and the agent who contributed them. "
        "Use this to cite evidence or challenge unsupported claims."
    )
    args_schema: Type[BaseModel] = LibraryReadInput

    def _run(self, session_id: str, query: str, n_results: int = 5) -> str:
        try:
            collection = _get_collection(session_id)

            count = collection.count()
            if count == 0:
                return "The shared library is currently empty. Run the research phase first."

            actual_n = min(n_results, count)
            results = collection.query(
                query_texts=[query],
                n_results=actual_n,
            )

            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            if not documents:
                return f"No relevant findings found for: '{query}'"

            lines: list[str] = [f"Library search results for: '{query}'\n"]
            for i, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances), 1):
                relevance = round((1 - dist) * 100, 1)
                agent = meta.get("agent_name", "Unknown")
                url = meta.get("source_url", "No URL")
                verified = meta.get("verified", False)
                verify_str = "✓ verified" if verified else "⚠ unverified"
                search_ref = meta.get("search_reference", "")
                snippet = doc[:300] + "…" if len(doc) > 300 else doc
                lines.append(f"[{i}] Relevance: {relevance}%  |  Contributed by: {agent}")
                lines.append(f"    Source: {url}  ({verify_str})")
                if search_ref:
                    lines.append(f"    Trace: {search_ref}")
                lines.append(f"    {snippet}")
                lines.append("")

            return "\n".join(lines)

        except Exception as exc:
            return f"Library read failed: {exc}"


# ------------------------------------------------------------------ #
# Factory
# ------------------------------------------------------------------ #


def create_library_tools() -> tuple[LibraryWriteTool, LibraryReadTool]:
    """Return a (write, read) pair of library tools."""
    return LibraryWriteTool(), LibraryReadTool()
