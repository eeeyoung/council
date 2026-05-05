"""
tests/test_research.py

Stage 2 tests for tools and the research crew.
Unit tests do NOT make real network calls or LLM calls.
Integration test is skipped by default.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from council.state import CouncilState, ExpertDefinition
from council.tools.library_tool import (
    LibraryReadTool,
    LibraryWriteTool,
    reset_library,
)


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def sample_state() -> CouncilState:
    state = CouncilState(query="Is dark matter a WIMP or an axion?")
    state.session_id = "test0001"
    state.experts = [
        ExpertDefinition(
            name="Dr. Lena Hartmann",
            discipline="Theoretical Astrophysics",
            bias="Prefers WIMP-based dark matter models",
            persona_prompt="A meticulous theorist who insists on mathematical elegance.",
        ),
        ExpertDefinition(
            name="Prof. James Okoro",
            discipline="Experimental Particle Physics",
            bias="Skeptical of unfalsifiable theories",
            persona_prompt="Demands reproducible experimental evidence above all.",
        ),
    ]
    return state


@pytest.fixture(autouse=True)
def clean_library(sample_state):
    """Ensure the library is clean before and after each test."""
    reset_library(sample_state.session_id)
    yield
    reset_library(sample_state.session_id)


# ------------------------------------------------------------------ #
# LibraryWriteTool tests
# ------------------------------------------------------------------ #


def test_library_write_success(sample_state):
    """Store a finding — URL may be unverifiable (404/timeout) but should still store."""
    tool = LibraryWriteTool()
    result = tool._run(
        session_id=sample_state.session_id,
        content="WIMPs are thermally produced in the early universe.",
        source_url="https://example.com/wimp-paper",
        agent_name="Dr. Lena Hartmann",
    )
    # example.com/wimp-paper returns 404, so we get "STORED (unverified)"
    assert "STORED" in result
    assert "example.com" in result


def test_library_write_rejects_invalid_url(sample_state):
    """Made-up strings should be rejected, not stored."""
    tool = LibraryWriteTool()
    result = tool._run(
        session_id=sample_state.session_id,
        content="Some finding.",
        source_url="I made this up",
        agent_name="Dr. Test",
    )
    assert "REJECTED" in result
    assert "Invalid" in result or "source_url" in result.lower()


def test_library_write_with_search_reference(sample_state):
    """search_reference should be accepted and stored."""
    tool = LibraryWriteTool()
    result = tool._run(
        session_id=sample_state.session_id,
        content="Finding with traceability.",
        source_url="https://example.com/traced",
        agent_name="Dr. Test",
        search_reference="from search result #3",
    )
    assert "STORED" in result


def test_library_write_multiple(sample_state):
    tool = LibraryWriteTool()
    for i in range(3):
        tool._run(
            session_id=sample_state.session_id,
            content=f"Finding number {i} about dark matter.",
            source_url=f"https://example.com/paper-{i}",
            agent_name="Dr. Lena Hartmann",
        )
    read_tool = LibraryReadTool()
    result = read_tool._run(
        session_id=sample_state.session_id,
        query="dark matter",
        n_results=3,
    )
    assert "Finding number" in result


def test_library_write_deduplication(sample_state):
    """Same content + URL written twice should not create duplicate entries."""
    tool = LibraryWriteTool()
    kwargs = dict(
        session_id=sample_state.session_id,
        content="Axions are a compelling dark matter candidate.",
        source_url="https://example.com/axion",
        agent_name="Prof. James Okoro",
    )
    tool._run(**kwargs)
    tool._run(**kwargs)  # duplicate

    read_tool = LibraryReadTool()
    result = read_tool._run(
        session_id=sample_state.session_id,
        query="axion dark matter",
        n_results=10,
    )
    # Should only appear once (deterministic ID)
    assert result.count("example.com/axion") == 1


# ------------------------------------------------------------------ #
# LibraryReadTool tests
# ------------------------------------------------------------------ #


def test_library_read_empty():
    """Use a dedicated session ID that no other test writes to."""
    isolated_session = "__empty_test__"
    reset_library(isolated_session)
    tool = LibraryReadTool()
    result = tool._run(
        session_id=isolated_session,
        query="anything",
    )
    assert "empty" in result.lower()
    reset_library(isolated_session)


def test_library_read_returns_results(sample_state):
    write = LibraryWriteTool()
    read = LibraryReadTool()

    write._run(
        session_id=sample_state.session_id,
        content="The XENON1T experiment set strong limits on WIMP-nucleon cross section.",
        source_url="https://xenon1t.example.com",
        agent_name="Prof. James Okoro",
    )

    result = read._run(
        session_id=sample_state.session_id,
        query="WIMP detection experiment",
    )
    assert "XENON1T" in result or "xenon1t" in result.lower()
    assert "Prof. James Okoro" in result


def test_library_read_n_results_capped(sample_state):
    """Requesting more results than available should not crash."""
    write = LibraryWriteTool()
    write._run(
        session_id=sample_state.session_id,
        content="Only one finding in the library.",
        source_url="https://example.com/one",
        agent_name="Dr. Lena Hartmann",
    )

    read = LibraryReadTool()
    result = read._run(
        session_id=sample_state.session_id,
        query="finding",
        n_results=20,  # More than available
    )
    assert "Only one finding" in result


# ------------------------------------------------------------------ #
# Search tool import test (no network call)
# ------------------------------------------------------------------ #


def test_search_tool_imports():
    from council.tools.search_tool import WebSearchTool, create_search_tool
    tool = create_search_tool()
    assert tool.name == "web_search"
    assert "search" in tool.description.lower()


# ------------------------------------------------------------------ #
# PDF tool import test (no file access)
# ------------------------------------------------------------------ #


def test_pdf_tool_missing_file():
    from council.tools.pdf_tool import PDFParserTool
    tool = PDFParserTool()
    result = tool._run(source="/nonexistent/path/paper.pdf")
    assert "failed" in result.lower() or "not found" in result.lower()


# ------------------------------------------------------------------ #
# Expert agent factory test (no LLM call)
# ------------------------------------------------------------------ #


def test_expert_agent_builds(sample_state):
    """
    Expert agent factory should create agents with correct role names.
    crewAI validates Agent.llm against BaseLLM, so we use a real LLM string
    or skip if the key isn't available.
    """
    import os

    from council.agents.expert import build_expert_agent
    from council.tools.library_tool import LibraryReadTool, LibraryWriteTool
    from council.tools.pdf_tool import PDFParserTool
    from council.tools.search_tool import WebSearchTool
    from council.config import build_llm

    api_key = os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith(("sk-xxxxx", "AIzaSyXXX")):
        pytest.skip("No valid API key available for agent construction")

    llm = build_llm()

    agent = build_expert_agent(
        expert=sample_state.experts[0],
        search_tool=WebSearchTool(),
        library_write=LibraryWriteTool(),
        library_read=LibraryReadTool(),
        pdf_tool=PDFParserTool(),
        llm=llm,
    )

    assert "Astrophysics" in agent.role or "Expert" in agent.role
    assert len(agent.tools) == 4


# ------------------------------------------------------------------ #
# Integration test (requires real API keys + network)
# ------------------------------------------------------------------ #


@pytest.mark.skip(reason="Requires real API keys and network — run manually")
def test_full_research_integration():
    """
    Full end-to-end research phase test.
    Run with: uv run pytest tests/test_research.py -k integration -s
    """
    from council.crews.research_crew import run_research

    state = CouncilState(
        query="Is dark matter a WIMP or an axion?",
        max_experts=2,
    )
    state.experts = [
        ExpertDefinition(
            name="Dr. Lena Hartmann",
            discipline="Theoretical Astrophysics",
            bias="Prefers WIMP models",
            persona_prompt="A meticulous theorist.",
        ),
        ExpertDefinition(
            name="Prof. James Okoro",
            discipline="Experimental Particle Physics",
            bias="Skeptical",
            persona_prompt="Demands evidence.",
        ),
    ]

    result = run_research(state)

    assert result.status == "debating"
    assert len(result.research_summaries) >= 2
    for expert in state.experts:
        assert expert.name in result.research_summaries
        print(f"\n{expert.name}:\n{result.research_summaries[expert.name][:200]}")
