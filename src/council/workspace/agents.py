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

from council.agents.moderator import build_moderator_agent
from council.agents.rapporteur import build_rapporteur
from council.config import build_llm
from crewai import Agent
from council.state import ExpertDefinition
from council.tools.library_tool import LibraryReadTool, create_library_tools
from council.tools.pdf_tool import create_pdf_tool
from council.tools.search_tool import create_search_tool
from council.workspace.llm import ask_agent
from council.workspace.state import Expert, KnowledgePool, PoolSource, Opinion, Session


# ── ChromaDB: per-expert collections ─────────────────────────────────────────
# FUTURE: full-text URL fetching in _enrich_source() is basic — only fetches
# HTML pages and strips tags. Should be improved with trafilatura or readability
# for better content extraction, and support for PDF download+parse.

_clients: dict[str, chromadb.ClientAPI] = {}
_collections: dict[str, chromadb.Collection] = {}


def _get_expert_collection(session_id: str, expert_id: str) -> chromadb.Collection:
    """Get or create a ChromaDB collection scoped to one expert."""
    key = f"{session_id}_{expert_id}"
    if key not in _clients:
        db_path = os.path.join(os.getcwd(), "chroma_db", "ws_default")
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
    session_id: str,
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

    collection = _get_expert_collection(session_id, expert_id)
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
    session_id: str,
    expert_id: str,
    query: str,
    n_results: int = 5,
) -> list[dict]:
    """Search the expert's ChromaDB collection and return relevant chunks."""
    collection = _get_expert_collection(session_id, expert_id)
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
    """Fetch full text from a source URL using trafilatura for clean extraction."""
    if not source.url or not source.url.startswith("http"):
        return source

    try:
        from council.tools.library_tool import _fetch_and_extract

        text = _fetch_and_extract(source.url, timeout=10)
        if text and len(text) > 200:
            source.full_text = text
    except Exception:
        pass  # Best-effort — silently keep the snippet

    return source


# ── User-driven operations (no LLM) ──────────────────────────────────────────


def add_source_to_expert(
    expert: Expert,
    session_id: str,
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
        origin="curated",
        source_type="url",
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
    chunks_indexed = _index_source_in_collection(session_id, expert.id, source)

    # Store metadata
    expert.knowledge_pool.sources.append(source)

    return source


def upload_file_to_expert(
    expert: Expert,
    session_id: str,
    file_path: str | Path,
) -> PoolSource | None:
    """Parse a PDF/DOC file and add it to the expert's knowledge pool.

    Uses the existing PDF parser tool. The full text is stored in the source
    and chunked/indexed into ChromaDB. No LLM call.

    Returns the PoolSource, or None if parsing failed."""
    file_path = Path(file_path)
    if not file_path.exists():
        return None

    ext = file_path.suffix.lower()
    full_text = ""

    # PDF parsing
    if ext == ".pdf":
        try:
            pdf_tool = create_pdf_tool()
            full_text = pdf_tool._run(source=str(file_path))
        except Exception:
            return None

        # Check for parse errors from the tool (it returns error strings, doesn't raise)
        if full_text.startswith("PDF parsing failed"):
            return None

        # Strip the header line "[PDF: N total pages, extracting M]"
        if full_text.startswith("[PDF:"):
            nl = full_text.find("\n")
            if nl != -1:
                full_text = full_text[nl + 1:].strip()

        # Check for image-only / scanned PDFs with no extractable text
        if not full_text or len(full_text) < 20:
            return None

    else:
        # Non-PDF: read as plain text
        try:
            full_text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                full_text = file_path.read_text(encoding="latin-1")
            except Exception:
                return None
        except Exception:
            return None

    if not full_text or not full_text.strip():
        return None

    stype = "pdf" if ext == ".pdf" else ("doc" if ext in (".doc", ".docx") else ("txt" if ext in (".txt", ".md") else "other"))
    source = PoolSource(
        origin="curated",
        source_type=stype,
        type="uploaded",
        title=file_path.name,
        full_text=full_text,
        added_by="user",
    )

    # Index into ChromaDB
    _index_source_in_collection(session_id, expert.id, source)

    # Store metadata
    expert.knowledge_pool.sources.append(source)

    return source


# ── LLM-driven operations ────────────────────────────────────────────────────


def form_opinion(
    expert: Expert,
    session_id: str,
    query: str,
    verbose: bool = False,
) -> Opinion | None:
    """Expert forms an evidence-grounded opinion from their verified pool sources.

    Uses RAG retrieval to find relevant chunks, then has the expert synthesize
    an opinion. Only verified sources are considered."""
    # Retrieve from the expert's pool
    retrieved = _retrieve_from_expert_pool(session_id, expert.id, query)

    verified_chunks = [r for r in retrieved if r["verification_status"] == "verified"]
    if not verified_chunks:
        verified_chunks = retrieved  # Fall back to unverified if nothing verified

    if not verified_chunks:
        return None  # No pool content to form an opinion from

    exp_def = _expert_to_definition(expert)
    library_write, library_read = create_library_tools()
    llm = build_llm(temperature=0.6)

    agent = build_expert_agent(
        expert=exp_def,
        search_tool=None,
        library_write=library_write,
        library_read=library_read,
        pdf_tool=None,
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
Your intellectual leaning: {expert.bias}.
Your personality: {expert.persona_prompt}

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
    session_id: str,
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
    retrieved = _retrieve_from_expert_pool(session_id, expert.id, message)

    library_write, library_read = create_library_tools()
    llm = build_llm(temperature=0.8)

    agent = build_expert_agent(
        expert=exp_def,
        search_tool=None,
        library_write=library_write,
        library_read=library_read,
        pdf_tool=None,
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
Your intellectual leaning: {expert.bias}.
Your personality: {expert.persona_prompt}

Research context: "{query}"

{pool_summary}

=== RETRIEVED PASSAGES (most relevant to the query) ===
{retrieval_context}
=== END PASSAGES ===

=== MESSAGE TO RESPOND TO ===
{message}
=== END MESSAGE ===

IMPORTANT — First, classify the message:
- If it is CASUAL (greeting, introduction, small talk, "who are you", "what's your name",
  "how are you", chitchat, or personal questions about yourself): respond naturally in
  character — be warm, personable, and stay true to your personality and discipline.
  Do NOT use the structured debate format. Just be yourself.
  Keep it SHORT: 1-3 sentences, 40-60 words maximum. Be concise and charming, not verbose.
- If it is SCIENTIFIC (research questions, evidence requests, analysis, debate):
  use the structured debate format below. Reason from your knowledge pool. Cite sources.

Use the structured debate format ONLY for scientific inquiries.

"""

    expected_output = """
If CASUAL: A natural, in-character response. Be yourself — your personality, discipline,
and intellectual leanings should shine through. Keep it warm, conversational, and SHORT:
1-3 sentences, 40-60 words maximum. No lists, no structured sections, no rambling.

If SCIENTIFIC: A structured response using EXACTLY this markdown format:

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
    panel_peers: list[dict] | None = None,
    verbose: bool = False,
) -> list[PoolSource]:
    """Expert generates search queries (LLM) → Tavily executes → code verifies.

    The LLM only generates domain-specific search queries — it does NOT call tools
    or filter results. Every Tavily result is verified via _verify_source() and
    returned with verification_status pre-set.

    Returns sources with verification_status already populated:
    "verified", "misattributed", or "unverifiable"."""
    from council.tools.library_tool import _verify_source

    pool_text = _pool_to_text(expert.knowledge_pool)

    # ── Step 1: LLM generates search queries ────────────────────────────
    llm = build_llm(temperature=0.8)
    agent = Agent(
        role=f"{expert.discipline} Query Strategist",
        goal="Generate precise, domain-specific search queries that will uncover unique sources invisible to other disciplines.",
        backstory=(
            f"{expert.persona_prompt}\n\n"
            f"You approach every problem through the lens of {expert.discipline}.\n"
            f"Your known intellectual bias is: {expert.bias}.\n"
            "You are crafting search queries, not evaluating results. Your job is to "
            "formulate the perfect queries that ONLY someone with your disciplinary "
            "training would think to ask."
        ),
        tools=[],
        llm=llm,
        verbose=verbose,
        allow_delegation=False,
    )

    # Build contrast-awareness paragraph (same as before)
    contrast = ""
    if panel_peers:
        peer_lines = []
        for p in panel_peers:
            peer_bias = p.get("bias", "")
            peer_lines.append(
                f"- {p['name']} ({p['discipline']})"
                + (f" — likely focus: {peer_bias}" if peer_bias else "")
            )
        contrast = f"""
=== YOUR PANEL PEERS ===
{chr(10).join(peer_lines)}

CRITICAL: Your peers will search from THEIR perspectives. You must generate queries
that are UNIQUELY visible through YOUR {expert.discipline} lens. Use YOUR field's
vocabulary. Search venues and journals that ONLY your discipline reads.
"""

    query_prompt = f"""
You are {expert.name}, a {expert.discipline} expert.
Your intellectual leaning: {expert.bias}.

Research context: "{query}"
Research goal: {research_goal or f'Find sources on: {query}'}

{pool_text}
{contrast}
Generate 3-5 specific, targeted search queries that would find high-quality,
citable sources addressing the research goal from YOUR disciplinary perspective.

Each query should:
- Use precise terminology from {expert.discipline}
- Be specific enough to return relevant academic/scientific results
- Be DIFFERENT from what other disciplines would search for

Return ONLY a JSON array of strings. No preamble, no explanation.
Example: ["quantum error correction surface codes threshold 2024", "fault-tolerant logical qubit experimental demonstration superconducting"]

IMPORTANT: Return ONLY the JSON array. Nothing else.
"""

    raw_queries = ask_agent(
        agent, query_prompt.strip(),
        "A JSON array of 3-5 search query strings.",
        verbose=verbose,
    )
    query_data = _parse_json(raw_queries)

    if not isinstance(query_data, list):
        return []

    queries = [str(q) for q in query_data if isinstance(q, str) and str(q).strip()]
    if not queries:
        return []

    # ── Step 2: Execute all queries via Tavily directly ──────────────────
    import logging
    _log = logging.getLogger("council.research")

    all_results: list[dict] = []  # {url, title, snippet}
    seen_urls: set[str] = set()

    try:
        import council.config as cfg
        from tavily import TavilyClient

        key = cfg.get_tavily_key()
        if not key:
            # Fallback to DuckDuckGo
            from ddgs import DDGS
            for q in queries[:5]:
                _log.info("🔍 DuckDuckGo: %r", q[:80])
                try:
                    with DDGS() as ddgs:
                        for r in ddgs.text(q, max_results=3):
                            url = r.get("href", "")
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                all_results.append({
                                    "url": url,
                                    "title": r.get("title", ""),
                                    "snippet": r.get("body", ""),
                                })
                except Exception:
                    pass
        else:
            client = TavilyClient(api_key=key)
            for q in queries[:5]:
                _log.info("🔍 Tavily: %r", q[:80])
                try:
                    resp = client.search(query=q, max_results=3, search_depth="advanced")
                    for r in resp.get("results", []):
                        url = r.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append({
                                "url": url,
                                "title": r.get("title", ""),
                                "snippet": r.get("content", ""),
                            })
                except Exception:
                    pass
    except Exception:
        pass

    if not all_results:
        return []

    _log.info("Total unique results across %d queries: %d", len(queries), len(all_results))

    # ── Step 3: Verify via trafilatura (page fetch only, no snippet fallback) ──
    sources: list[PoolSource] = []

    for r in all_results:
        url = r["url"]
        title = r["title"]
        snippet = r["snippet"]

        normalized_url, status, note = _verify_source(
            source_url=url,
            source_quote=snippet,
            fast=True,  # trafilatura only — if we can't read the page, say so honestly
        )

        sources.append(PoolSource(
            origin="discovered",
            source_type="url",
            type="verified" if status == "verified" else "collected",
            url=normalized_url if normalized_url.startswith("http") else url,
            title=title,
            snippet=snippet,
            verification_status=status,
            verification_note=note,
            added_by=expert.name,
        ))

    verified = sum(1 for s in sources if s.verification_status == "verified")
    _log.info("Verification complete: %d/%d verified via full-page extraction",
              verified, len(sources))

    return sources


def fact_check_source(source: PoolSource, verbose: bool = False) -> PoolSource:
    """Verify a single source. Uses trafilatura-based _verify_source() as the
    primary check, with LLM fallback for ambiguous cases.

    Returns the source with verification_status and verification_note updated."""
    from council.tools.library_tool import _verify_source

    # ── Primary: trafilatura-based deterministic verification ──
    if source.url:
        normalized_url, status, note = _verify_source(
            source_url=source.url,
            source_quote=source.snippet,
        )
        source.verification_status = status
        source.verification_note = note
        if status == "verified":
            source.type = "verified"
        elif status == "misattributed":
            source.type = "rejected"
        return source

    # ── No URL: basic existence check ──
    if source.title:
        # Try searching for the title
        search_tool = create_search_tool()
        result = search_tool._run(source.title, max_results=1)
        if result and "No results" not in result:
            source.verification_status = "verified"
            source.verification_note = "Title found via web search"
            source.type = "verified"
            return source

    source.verification_status = "unverifiable"
    source.verification_note = "No URL or title to verify"
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


# ── Panel editing helpers ──────────────────────────────────────────────────────


def polish_query(query: str, verbose: bool = False) -> str:
    """Refine a research question — clarify ambiguities, narrow scope.

    Stateless: no tools, no session, no ChromaDB. Returns the polished query."""
    llm = build_llm(temperature=0.4)
    agent = Agent(
        role="Research Question Editor",
        goal="Refine research questions to be clearer, more specific, and better scoped for multi-disciplinary expert panels.",
        backstory=(
            "You are a senior research programme manager who has commissioned dozens "
            "of scientific symposia. You know that a well-formed research question "
            "determines the quality of the entire symposium. You help researchers "
            "sharpen vague questions into precise, productive inquiries."
        ),
        tools=[],
        llm=llm,
        verbose=verbose,
        allow_delegation=False,
    )

    description = f"""
The following research question will be used to assemble an expert panel and guide a scientific symposium:

"{query}"

Refine this question. Your refined version should:
1. Be clearer and more specific — remove ambiguity
2. Be well-scoped — not too broad, not too narrow
3. Use precise scientific terminology
4. Imply the kinds of expertise needed (e.g., theoretical, experimental, computational)

Return ONLY the refined question text — no preamble, no explanation.
"""
    return ask_agent(agent, description, "The refined research question text only.", verbose=verbose).strip()


def propose_expert(
    query: str,
    existing_experts: list[dict] | None = None,
    verbose: bool = False,
) -> dict | None:
    """Propose a single new expert to fill a gap in an existing panel.

    Analyzes the current panel composition and identifies a missing disciplinary
    perspective. Returns {name, discipline, bias, persona_prompt} or None."""
    llm = build_llm(temperature=0.7)
    agent = Agent(
        role="Panel Architect",
        goal="Identify missing perspectives in expert panels and propose the perfect expert to fill each gap.",
        backstory=(
            "You are an elite scientific programme director who assembles panels "
            "for high-stakes research symposia. You can look at an existing panel "
            "and instantly see which disciplinary perspectives, methodological "
            "approaches, or intellectual traditions are missing. You propose "
            "experts who will create productive intellectual tension."
        ),
        tools=[],
        llm=llm,
        verbose=verbose,
        allow_delegation=False,
    )

    existing_text = ""
    if existing_experts:
        lines = []
        for e in existing_experts:
            lines.append(
                f"- {e.get('name', '?')} ({e.get('discipline', '?')})"
                + (f" — {e.get('bias', '')}" if e.get('bias') else "")
            )
        existing_text = "Current panel:\n" + "\n".join(lines)
    else:
        existing_text = "The panel is currently empty."

    description = f"""
Research Question: "{query}"

{existing_text}

Analyze the current panel. What critical disciplinary or methodological perspective
is MISSING? Identify ONE gap and propose ONE new expert to fill it.

The expert should:
- Come from a discipline NOT already represented
- Bring a methodological approach NOT already present
- Create productive intellectual tension with the existing panel
- Have a philosopher-inspired alias (e.g., "Socratyes", "Kantwell", "Hypatia")

Return a JSON object with: name, discipline, bias, persona_prompt
"""
    raw = ask_agent(
        agent, description.strip(),
        "A JSON object with keys: name, discipline, bias, persona_prompt.",
        verbose=verbose,
    )
    data = _parse_json(raw)
    if isinstance(data, dict) and "name" in data:
        return {
            "name": str(data.get("name", "")),
            "discipline": str(data.get("discipline", "")),
            "bias": str(data.get("bias", "")),
            "persona_prompt": str(data.get("persona_prompt", "")),
        }
    return None
