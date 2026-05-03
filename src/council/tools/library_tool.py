"""
council/tools/library_tool.py

Shared Research Library — ChromaDB-backed vector store shared across ALL agents
in a COUNCIL session.

Design:
- One in-memory ChromaDB collection per session_id (created on first access)
- Agents WRITE findings with LibraryWriteTool
- Agents READ (semantic search) with LibraryReadTool
- The singleton pattern ensures all agents in the same process share the same store
- Persistent mode (Phase 4) upgrades to PersistentClient by swapping _get_client()

Both tools are exposed as crewAI BaseTool instances.
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING, Type

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


def _get_collection(session_id: str) -> chromadb.Collection:
    """
    Return (or create) the ChromaDB collection for this session.
    Uses EphemeralClient (in-memory) — sufficient for Stage 2.
    Stage 4 will upgrade to PersistentClient.
    """
    if session_id not in _clients:
        db_path = os.path.join(os.getcwd(), "chroma_db", session_id)
        os.makedirs(db_path, exist_ok=True)
        _clients[session_id] = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False)
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
        description="The URL or citation source for this content.",
    )
    agent_name: str = Field(..., description="Your expert name.")


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
    Call this after finding relevant information via web search to make your
    findings available to other agents and the RecorderAgent.
    """

    name: str = "library_write"
    description: str = (
        "Save a research finding to the shared COUNCIL library. "
        "Provide: the session_id, the content (a key finding or quote), "
        "the source_url, and your agent_name. "
        "Other agents and the recorder will be able to retrieve this evidence."
    )
    args_schema: Type[BaseModel] = LibraryWriteInput

    def _run(
        self,
        session_id: str,
        content: str,
        source_url: str,
        agent_name: str,
    ) -> str:
        try:
            collection = _get_collection(session_id)

            # Deterministic ID to avoid duplicate writes
            doc_id = hashlib.md5(f"{agent_name}:{source_url}:{content[:100]}".encode()).hexdigest()

            collection.add(
                documents=[content],
                metadatas=[{"source_url": source_url, "agent_name": agent_name}],
                ids=[doc_id],
            )
            return f"✓ Finding stored in library (id={doc_id[:8]}). Source: {source_url}"

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
        "relevant to your query. Returns matching findings with their source URLs "
        "and the agent who contributed them. "
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
                snippet = doc[:300] + "…" if len(doc) > 300 else doc
                lines.append(f"[{i}] Relevance: {relevance}%  |  Contributed by: {agent}")
                lines.append(f"    Source: {url}")
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
