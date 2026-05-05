# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project overview

COUNCIL is a multi-agent scientific brainstorming framework using CrewAI and
ChromaDB. It runs a 5-phase pipeline (A: Panel Curation, B: Parallel Research,
C: Sequential Symposium/Debate, D: Audit Loop, E: Final Dossier) and serves a
web GUI ("Mission Control") via FastAPI + SSE for live and review modes.

## Commands

```bash
uv run pytest tests/ -v          # Run tests
uv run council "query"            # CLI symposium
uv run python -m council.main "query" --experts 5 --verbose --no-confirm
uv run python -m council.server               # Web server (review mode)
uv run python -m council.server --mode live   # Web server (live mode)
```

## Architecture

```
config/agents.yaml   — Agent role/goal/backstory definitions
config/tasks.yaml    — Task descriptions and expected output formats
src/council/agents/  — One file per agent (thin wrappers reading YAML config)
src/council/crews/   — Phase implementations (research, debate, audit, dossier)
src/council/tools/   — WebSearchTool, LibraryWriteTool, LibraryReadTool, PDFParserTool
src/council/state.py — CouncilState Pydantic model (the single data structure)
src/council/manifest.py — Shared manifest writer (one source of truth)
gui/                 — Mission Control web dashboard (HTML/JS/CSS)
```

## Key patterns

- All agents extend `crewai.Agent` and read their config from YAML
- `CouncilState` is the central data model passed through all phases
- `transcript_text` renders debate entries with markers: `[Turn N]` for experts,
  `[RAPPORTEUR]`/`[DISCUSSANT]` for audit entries
- Live mode (SSE) emitter: `live_runner.py`. Review/replay emitter: `simulator.py`.
  Both must emit the same event shapes.
- Source verification happens inline at `library_write` — URLs/DOIs are validated
  before storage
- The Fact-Checker has both `library_read` and `web_search` tools
- Agent temperatures: Fact-Checker=0.2, Discussant=0.2, Rapporteur=0.4,
  Aggregator=0.4, Dossier Author=0.6, Moderator=0.7, Experts=0.8

## When adding a new agent

1. Add entry to `config/agents.yaml` (role, goal, backstory)
2. Add task(s) to `config/tasks.yaml`
3. Create agent file in `src/council/agents/` with `build_<name>()` function
4. Use the agent in the appropriate crew file
5. Update `README.md` agent table and project structure

## When changing the pipeline

- `main.py` — CLI path (synchronous)
- `live_runner.py` — Live mode SSE path (async generator wrapping sync calls)
- `simulator.py` — Review/replay SSE path (reads files, no LLM)
- `state.py` — `CouncilState.status` drives the phase transitions
- All three paths (CLI, live, replay) should produce semantically equivalent
  output files and manifest entries

## Considerations

- `max_iter=8` on experts (room for search + writes + report)
- SSE events from `live_runner.py` and `simulator.py` must emit the same JSON
  shapes — the frontend has one set of listeners
- Transcript markers: `state.transcript_text` produces `[RAPPORTEUR]` and
  `[DISCUSSANT]` markers for audit-phase entries — the frontend and simulator
  regex must match
- The frontend detects audit entries by name matching: `'Rapporteur'` and
  `'Discussant'`
- Consensus files are named `consensus_r{round}.md` where round is `audit_round`
  (0-indexed)
