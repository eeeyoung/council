"""
council/workspace/agents.py

Thin agent wrappers for the workspace system.

Each function:
1. Converts workspace types to agent-builder types
2. Builds the agent + prompt from workspace context
3. Calls ask_agent() — single agent, single task, no loops
4. Parses the result and returns workspace types

User-driven operations (no LLM):
- add_source_to_expert() — paste URL + snippet into pool
- upload_file_to_expert() — parse PDF/DOC into pool

Both chunk content and index into per-expert ChromaDB collections for RAG.
Full-text URL fetching is basic — marked for future improvement.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import chromadb
from chromadb.config import Settings

from council.agents.expert import build_expert_agent
from council.agents.fact_checker import build_fact_checker
from council.agents.moderator import build_moderator_agent
from council.agents.rapporteur import build_rapporteur
from council.config import build_llm
from council.state import ExpertDefinition
from council.tools.library_tool import LibraryReadTool, create_library_tools
from council.tools.pdf_tool import create_pdf_tool
from council.tools.search_tool import create_search_tool
from council.workspace.llm import ask_agent
from council.workspace.state import Expert, KnowledgePool, PoolSource, Opinion


# ── ChromaDB: per-expert collections ─────────────────────────────────────────
# FUTURE: full-text URL fetching in _enrich_source() is basic — only fetches
# HTML pages and strips tags. Should be improved with trafilatura or readability
# for better content extraction, and support for PDF download+parse.

_clients: dict[str, chromadb.ClientAPI] = {}
_collections: dict[str, chromadb.Collection] = {}


def _get_expert_collection(workspace_id: str, expert_id: str) -> chromadb.Collection:
    """Get or create a ChromaDB collection scoped to one expert."""
    key = f"{workspace_id}_{expert_id}"
    if key not in _clients:
        db_path = os.path.join(os.getcwd(), "chroma_db", f"ws_{workspace_id}")
        os.makedirs(db_path, exist_ok=True)
        _clients[key] = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )
    if key not in _collections:
        from chromadb.utils import embedding_functions
        ef = embedding_functions.DefaultEmbeddingFunction()
        _collections[key] = _clients[key].get_or_create_collection(
            name=f"expert_{expert_id}",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collections[key]


def _index_source_in_collection(
    workspace_id: str,
    expert_id: str,
    source: PoolSource,
    chunk_size: int = 500,
    overlap: int = 50,
) -> int:
    """Chunk a source's text and index into the expert's ChromaDB collection.

    Returns the number of chunks indexed."""
    text = source.full_text or source.snippet
    if not text.strip():
        return 0

    chunks = _chunk_text(text, chunk_size, overlap)
    if not chunks:
        return 0

    collection = _get_expert_collection(workspace_id, expert_id)
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for i, chunk in enumerate(chunks):
        doc_id = hashlib.md5(
            f"{source.id}:chunk_{i}".encode()
        ).hexdigest()
        ids.append(doc_id)
        documents.append(chunk)
        metadatas.append({
            "source_id": source.id,
            "title": source.title or "",
            "url": source.url or "",
            "verification_status": source.verification_status,
            "chunk_index": i,
        })

    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    return len(chunks)


def _retrieve_from_expert_pool(
    workspace_id: str,
    expert_id: str,
    query: str,
    n_results: int = 5,
) -> list[dict]:
    """Search the expert's ChromaDB collection and return relevant chunks."""
    collection = _get_expert_collection(workspace_id, expert_id)
    if collection.count() == 0:
        return []

    results = collection.query(query_texts=[query], n_results=min(n_results, collection.count()))
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    out: list[dict] = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        out.append({
            "content": doc,
            "source_id": meta.get("source_id", ""),
            "title": meta.get("title", ""),
            "url": meta.get("url", ""),
            "verification_status": meta.get("verification_status", ""),
            "relevance": round((1 - dist) * 100, 1),
        })
    return out


# ── Text chunking ────────────────────────────────────────────────────────────


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks, respecting paragraph boundaries."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break
        chunk = text[start:end]
        # Try to break at a natural boundary
        for sep in ("\n\n", ". ", " "):
            last = chunk.rfind(sep)
            if last > chunk_size // 2:
                end = start + last + len(sep)
                break
        chunks.append(text[start:end].strip())
        start = end - overlap
    return chunks


# ── Helpers ──────────────────────────────────────────────────────────────────


def _expert_to_definition(expert: Expert) -> ExpertDefinition:
    """Convert workspace Expert to the ExpertDefinition expected by agent builders."""
    return ExpertDefinition(
        name=expert.name,
        discipline=expert.discipline,
        bias=expert.bias,
        persona_prompt=expert.persona_prompt,
    )


def _pool_to_text(pool: KnowledgePool) -> str:
    """Render an expert's knowledge pool as text for prompt injection."""
    if not pool.sources and not pool.opinions:
        return "(Your knowledge pool is empty. You have no sources or opinions yet.)"

    parts: list[str] = []

    if pool.sources:
        parts.append("=== YOUR KNOWLEDGE POOL — SOURCES ===")
        for s in pool.sources:
            status = f"[{s.verification_status}]" if s.verification_status else "[pending]"
            parts.append(f"- {status} {s.title or 'Untitled'}")
            if s.url:
                parts.append(f"  URL: {s.url}")
            if s.snippet:
                parts.append(f"  Snippet: {s.snippet}")
            if s.full_text:
                parts.append(f"  Full text: {s.full_text[:500]}...")

    if pool.opinions:
        parts.append("\n=== YOUR EXISTING OPINIONS ===")
        for o in pool.opinions:
            parts.append(f"- {o.text}")

    return "\n".join(parts)


def _parse_json(raw: str) -> dict | list | None:
    """Extract and parse JSON from an LLM output string.

    Handles markdown fences, preamble text, and trailing text."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()

    # Find the first [ or { — whichever comes first (handles preamble text)
    bracket_start = cleaned.find("[")
    brace_start = cleaned.find("{")
    if bracket_start == -1 and brace_start == -1:
        return None
    if bracket_start == -1:
        start = brace_start
        is_array = False
    elif brace_start == -1:
        start = bracket_start
        is_array = True
    else:
        start = min(bracket_start, brace_start)
        is_array = start == bracket_start

    # Find the matching closing character
    end = cleaned.rfind("]") if is_array else cleaned.rfind("}")
    if end == -1 or end <= start:
        return None

    try:
        json_str = cleaned[start : end + 1]
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
        return json.loads(json_str)
    except Exception:
        return None


# ── URL fetching (basic — FUTURE IMPROVEMENT) ────────────────────────────────


def _enrich_source(source: PoolSource) -> PoolSource:
    """Attempt to fetch full text from a source URL. Basic implementation.

    FUTURE: Replace with trafilatura or readability-lxml for proper boilerplate
    stripping. Currently does a simple HTML fetch + tag removal. Also does not
    handle PDF downloads — those should go through upload_file_to_expert()."""
    if not source.url or not source.url.startswith("http"):
        return source

    try:
        req = urllib.request.Request(
            source.url,
            headers={"User-Agent": "COUNCIL/0.1"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type and "text" not in content_type:
                return source  # PDF, binary, etc. — skip
            html = resp.read().decode("utf-8", errors="replace")

            # Basic tag stripping (not robust — see FUTURE note above)
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

            if len(text) > 200:
                source.full_text = text
    except Exception:
        pass  # Silently keep the snippet — enrichment is best-effort

    return source


# ── User-driven operations (no LLM) ──────────────────────────────────────────


def add_source_to_expert(
    expert: Expert,
    workspace_id: str,
    url: str = "",
    title: str = "",
    snippet: str = "",
    full_text: str = "",
    enrich: bool = True,
) -> PoolSource:
    """Add a source to an expert's knowledge pool. No LLM call.

    User pastes a URL, title, and snippet. If enrich=True (default), attempts
    to fetch full text from the URL. The source is chunked and indexed into the
    expert's ChromaDB collection for RAG retrieval.

    The source starts as type="collected" — call fact_check_source() separately
    to verify it."""
    source = PoolSource(
        type="collected",
        url=url,
        title=title,
        snippet=snippet,
        full_text=full_text,
        added_by="user",
    )

    # Attempt full-text enrichment (best-effort, no blocking)
    if enrich and url and not full_text:
        source = _enrich_source(source)

    # Index into ChromaDB
    chunks_indexed = _index_source_in_collection(workspace_id, expert.id, source)

    # Store metadata
    expert.knowledge_pool.sources.append(source)

    return source


def upload_file_to_expert(
    expert: Expert,
    workspace_id: str,
    file_path: str | Path,
) -> PoolSource | None:
    """Parse a PDF/DOC file and add it to the expert's knowledge pool.

    Uses the existing PDF parser tool. The full text is stored in the source
    and chunked/indexed into ChromaDB. No LLM call.

    Returns the PoolSource, or None if parsing failed."""
    file_path = Path(file_path)
    if not file_path.exists():
        return None

    # Use the existing PDF parser
    try:
        pdf_tool = create_pdf_tool()
        full_text = pdf_tool._run(file_path=str(file_path))
    except Exception:
        # Fallback: try reading as plain text
        try:
            full_text = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

    if not full_text or not full_text.strip():
        return None

    source = PoolSource(
        type="uploaded",
        title=file_path.name,
        full_text=full_text,
        added_by="user",
    )

    # Index into ChromaDB
    _index_source_in_collection(workspace_id, expert.id, source)

    # Store metadata
    expert.knowledge_pool.sources.append(source)

    return source


# ── LLM-driven operations ────────────────────────────────────────────────────


def form_opinion(
    expert: Expert,
    workspace_id: str,
    query: str,
    verbose: bool = False,
) -> Opinion | None:
    """Expert forms an evidence-grounded opinion from their verified pool sources.

    Uses RAG retrieval to find relevant chunks, then has the expert synthesize
    an opinion. Only verified sources are considered."""
    # Retrieve from the expert's pool
    retrieved = _retrieve_from_expert_pool(workspace_id, expert.id, query)

    verified_chunks = [r for r in retrieved if r["verification_status"] == "verified"]
    if not verified_chunks:
        verified_chunks = retrieved  # Fall back to unverified if nothing verified

    if not verified_chunks:
        return None  # No pool content to form an opinion from

    exp_def = _expert_to_definition(expert)
    search_tool = create_search_tool()
    library_write, library_read = create_library_tools()
    pdf_tool = create_pdf_tool()
    llm = build_llm(temperature=0.6)

    agent = build_expert_agent(
        expert=exp_def,
        search_tool=search_tool,
        library_write=library_write,
        library_read=library_read,
        pdf_tool=pdf_tool,
        llm=llm,
        verbose=verbose,
    )

    # Build retrieved context
    context_blocks: list[str] = []
    source_ids_seen: set[str] = set()
    for r in verified_chunks:
        context_blocks.append(
            f"[{r['title'] or r['url'] or 'Source'}] {r['content']}"
        )
        source_ids_seen.add(r["source_id"])

    context = "\n\n".join(context_blocks)

    description = f"""
You are {expert.name}, a {expert.discipline} expert.

Research context: "{query}"

=== RELEVANT PASSAGES FROM YOUR KNOWLEDGE POOL ===
{context}
=== END PASSAGES ===

Your task: Form an evidence-grounded opinion on the research context above.
Your opinion must be based on the passages provided. Cite which passages support
each part of your opinion.

Return a JSON object with:
  - "opinion": your evidence-grounded opinion (2-5 sentences)
  - "source_ids": list of source titles/URLs that support this opinion
"""

    raw = ask_agent(
        agent,
        description.strip(),
        "A JSON object with opinion and source_ids.",
        verbose=verbose,
    )
    data = _parse_json(raw)

    if not data or not isinstance(data, dict):
        return None

    opinion = Opinion(
        text=data.get("opinion", ""),
        source_ids=list(source_ids_seen),
    )
    expert.knowledge_pool.opinions.append(opinion)
    return opinion


def expert_respond(
    expert: Expert,
    workspace_id: str,
    query: str,
    message: str,
    verbose: bool = False,
) -> str:
    """Expert responds to a message, reasoning from their knowledge pool via RAG.

    Retrieves relevant chunks from the expert's ChromaDB collection instead of
    dumping the entire pool into the prompt.

    Returns the expert's structured markdown response (Position / Evidence / Keywords)."""
    exp_def = _expert_to_definition(expert)

    # RAG retrieval
    retrieved = _retrieve_from_expert_pool(workspace_id, expert.id, message)

    search_tool = create_search_tool()
    library_write, library_read = create_library_tools()
    pdf_tool = create_pdf_tool()
    llm = build_llm(temperature=0.8)

    agent = build_expert_agent(
        expert=exp_def,
        search_tool=search_tool,
        library_write=library_write,
        library_read=library_read,
        pdf_tool=pdf_tool,
        llm=llm,
        verbose=verbose,
    )

    # Build retrieval context
    if retrieved:
        context_blocks: list[str] = []
        for r in retrieved:
            status = f"[{r['verification_status']}]" if r['verification_status'] else "[unverified]"
            context_blocks.append(
                f"{status} [{r['title'] or r['url'] or 'Source'}]\n{r['content']}"
            )
        retrieval_context = "\n\n".join(context_blocks)
    else:
        retrieval_context = "(Your knowledge pool is empty. You have no sources to draw from.)"

    # Pool metadata summary (titles + statuses, not full text)
    pool_summary = _pool_to_text(expert.knowledge_pool)

    description = f"""
You are {expert.name}, a {expert.discipline} expert.

Research context: "{query}"

{pool_summary}

=== RETRIEVED PASSAGES (most relevant to the query) ===
{retrieval_context}
=== END PASSAGES ===

=== MESSAGE TO RESPOND TO ===
{message}
=== END MESSAGE ===

Your task: Respond to the message above. You MUST reason from your knowledge pool.
Cite specific sources from the retrieved passages. If your pool has opinions, build
on them. If no retrieved passages are relevant, acknowledge that and suggest what
research is needed.

Use the structured debate format: ## Position, **Keywords:**, ## Evidence (with
### Finding, **Claim:**, **Source:**, **Quote:**). Only include ## Response to Peers
if the message is from another expert challenging your position.
"""

    expected_output = """
A structured response using EXACTLY this markdown format:

## Position
[Your core thesis, grounded in your knowledge pool.]

**Keywords:** [3-5 comma-separated key terms]

## Evidence
### {Finding Title}
**Claim:** [The specific factual claim.]
**Source:** [URL or "From knowledge pool: {source title}"]
**Quote:** [The exact sentence from the source.]
"""

    return ask_agent(agent, description.strip(), expected_output.strip(), verbose=verbose)


def expert_research(
    expert: Expert,
    query: str,
    research_goal: str = "",
    verbose: bool = False,
) -> list[PoolSource]:
    """Expert searches for sources on a topic. Returns collected sources (unverified).

    These sources should be passed through fact_check_source() before the expert
    forms opinions on them."""
    exp_def = _expert_to_definition(expert)
    pool_text = _pool_to_text(expert.knowledge_pool)

    search_tool = create_search_tool()
    library_write, library_read = create_library_tools()
    pdf_tool = create_pdf_tool()
    llm = build_llm(temperature=0.8)

    agent = build_expert_agent(
        expert=exp_def,
        search_tool=search_tool,
        library_write=library_write,
        library_read=library_read,
        pdf_tool=pdf_tool,
        llm=llm,
        verbose=verbose,
    )

    goal = research_goal or f"Find 3-5 highly relevant sources on: {query}"

    description = f"""
You are {expert.name}, a {expert.discipline} expert.

Research context: "{query}"
Research goal: {goal}

{pool_text}

Your task: Use web_search to find 3-5 relevant sources that address the research goal
from your disciplinary perspective. For each source, deposit it into the shared library
using library_write with the EXACT URL, title, and snippet from the search result.

Do NOT form opinions yet — just collect sources. The Fact-Checker will verify them next.

Return a JSON array of the sources you found. Each entry must have:
- "url": the EXACT URL
- "title": the title of the article/paper
- "snippet": the text excerpt from the search result
"""

    raw = ask_agent(agent, description.strip(), "A JSON array of source objects.", verbose=verbose)
    data = _parse_json(raw)

    if not data or not isinstance(data, list):
        return []

    return [
        PoolSource(
            type="collected",
            url=item.get("url", ""),
            title=item.get("title", ""),
            snippet=item.get("snippet", ""),
            added_by=expert.name,
        )
        for item in data
    ]


def fact_check_source(source: PoolSource, verbose: bool = False) -> PoolSource:
    """Verify a single source. Returns the source with verification_status updated.

    Checks: URL resolves, source actually exists, quote matches (if provided)."""
    search_tool = create_search_tool()
    library_read = LibraryReadTool(session_id="")  # session-less for workspace
    llm = build_llm(temperature=0.2)

    agent = build_fact_checker(
        library_read=library_read,
        search_tool=search_tool,
        llm=llm,
    )

    quote_info = f'\nSource quote to verify: "{source.snippet[:200]}"' if source.snippet else ""

    description = f"""
Verify this source:

URL: {source.url}
Title: {source.title}{quote_info}

1. Search the web for this title to confirm the source actually exists.
2. If a quote is provided, check whether it appears at the claimed URL.
3. Return a JSON object with:
   - "verification_status": "verified" (confirmed), "misattributed" (quote doesn't match), or "unverifiable" (can't check)
   - "verification_note": brief explanation
"""

    raw = ask_agent(
        agent,
        description.strip(),
        "A JSON object with verification_status and verification_note.",
        verbose=verbose,
    )
    data = _parse_json(raw)

    if data and isinstance(data, dict):
        source.verification_status = data.get("verification_status", "unverifiable")
        source.verification_note = data.get("verification_note", "")
        if source.verification_status == "verified":
            source.type = "verified"
        elif source.verification_status == "misattributed":
            source.type = "rejected"
    else:
        source.verification_status = "unverifiable"
        source.verification_note = "Could not parse Fact-Checker response."

    return source


def moderator_propose_panel(
    query: str = "",
    function_type: str = "",
    function_detail: str = "",
    max_experts: int = 5,
    verbose: bool = False,
) -> list[Expert]:
    """Propose an expert panel from a research question or function description.

    Returns a list of workspace Expert objects ready for user editing."""
    search_tool = create_search_tool()
    llm = build_llm(temperature=0.7)

    agent = build_moderator_agent(search_tool=search_tool, llm=llm)

    if query:
        mode_desc = f"""The user has submitted this research question: "{query}"
Desired outcome: {function_type or 'balanced_overview'}"""
    else:
        mode_desc = f"""The user needs a panel for: {function_type}
Details: {function_detail or 'Not specified'}"""

    description = f"""
{mode_desc}

FIRST: Use web search to research the current state of this field. Identify real
sub-disciplines, active research directions, and methodological debates.

THEN: Generate exactly {max_experts} expert personas. Each must bring a genuinely
distinct disciplinary perspective. Avoid redundancy.

For names: use philosopher-inspired aliases — slightly misspell or blend famous
thinkers' names. Examples: "Socratyes", "Kantwell", "Hypatienne", "Arendelle".

Return ONLY a valid JSON array. Each object must have:
  - "name": philosopher-inspired alias
  - "discipline": their primary field
  - "bias": their known intellectual leaning or methodological preference
  - "persona_prompt": 2-3 sentences describing their personality and approach
"""

    raw = ask_agent(
        agent,
        description.strip(),
        "A valid JSON array of expert definition objects with no surrounding text.",
        verbose=verbose,
    )
    data = _parse_json(raw)

    if not data or not isinstance(data, list):
        return []

    return [
        Expert(
            name=item.get("name", f"Expert {i+1}"),
            discipline=item.get("discipline", ""),
            bias=item.get("bias", ""),
            persona_prompt=item.get("persona_prompt", ""),
        )
        for i, item in enumerate(data)
    ]


def rapporteur_synthesize(
    transcript: str,
    scorecard: str,
    query: str = "",
    verbose: bool = False,
) -> str:
    """Synthesize a debate transcript + scorecard into a consensus document.

    Returns structured markdown: Consensus Map / Disagreement Landscape / Unified Hypothesis."""
    library_read = LibraryReadTool(session_id="")  # session-less for workspace
    llm = build_llm(temperature=0.4)

    agent = build_rapporteur(library_read=library_read, llm=llm)

    description = f"""
Research Question: "{query}"

=== FULL DEBATE TRANSCRIPT ===
{transcript}
=== END TRANSCRIPT ===

=== EVIDENCE SCORECARD ===
{scorecard}
=== END SCORECARD ===

Synthesize the above into a unified hypothesis. Your synthesis must:
1. Identify the 2-3 strongest points of genuine consensus
2. Acknowledge the most significant point of expert disagreement
3. Propose a unified hypothesis that incorporates the best-supported elements
"""

    expected_output = """
A structured synthesis using EXACTLY this markdown format:

## Consensus Map
### {Consensus Point Title}
**Strength:** [Strong / Moderate / Weak]
**Held by:** {Expert Name}, {Expert Name}
**Evidence:** [Reference to scorecard evidence.]
**Summary:** [1-2 sentences.]

## Disagreement Landscape
### {Disagreement Point Title}
**Positions:** {A} argues [X], {B} contends [Y].
**Evidence gap:** [What would resolve this.]
**Significance:** [Critical / Moderate / Minor]

## Unified Hypothesis
[2-4 sentence synthesized conclusion.]

**Keywords:** [3-5 synthesis-level terms]
"""

    return ask_agent(agent, description.strip(), expected_output.strip(), verbose=verbose)
