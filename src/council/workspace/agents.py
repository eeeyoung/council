"""
council/workspace/agents.py

Thin agent wrappers for the workspace system.

Each function:
1. Converts workspace types to agent-builder types
2. Builds the agent + prompt from workspace context
3. Calls ask_agent() — single agent, single task, no loops
4. Parses the result and returns workspace types
"""

from __future__ import annotations

import json
import re

from council.agents.expert import build_expert_agent
from council.agents.fact_checker import build_fact_checker
from council.agents.moderator import build_moderator_agent
from council.agents.rapporteur import build_rapporteur
from council.config import build_llm
from council.state import ExpertDefinition
from council.tools.library_tool import LibraryReadTool, LibraryWriteTool, create_library_tools
from council.tools.pdf_tool import create_pdf_tool
from council.tools.search_tool import create_search_tool
from council.workspace.llm import ask_agent
from council.workspace.state import Expert, KnowledgePool, PoolSource, Opinion


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
    """Extract and parse JSON from an LLM output string."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    start = cleaned.find("[") if cleaned.startswith("[") else cleaned.find("{")
    if start == -1:
        return None
    end = cleaned.rfind("]") if cleaned.startswith("[") else cleaned.rfind("}")
    if end == -1:
        return None
    try:
        json_str = cleaned[start : end + 1]
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
        return json.loads(json_str)
    except Exception:
        return None


# ── Agent wrappers ───────────────────────────────────────────────────────────

def expert_respond(
    expert: Expert,
    query: str,
    message: str,
    verbose: bool = False,
) -> str:
    """Expert responds to a message, reasoning from their knowledge pool.

    Returns the expert's structured markdown response (Position / Evidence / Keywords)."""
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

    description = f"""
You are {expert.name}, a {expert.discipline} expert.

Research context: "{query}"

{pool_text}

=== MESSAGE TO RESPOND TO ===
{message}
=== END MESSAGE ===

Your task: Respond to the message above. You MUST reason from your knowledge pool.
If your pool has relevant sources, cite them. If your pool has opinions, build on them.
If your pool is empty on this topic, acknowledge that and suggest what research is needed.

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
