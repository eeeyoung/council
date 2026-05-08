# Workspace Implementation Plan — `ws/dev` branch

## Principles

- **Flat over deep** — modules call each other directly, no plugin systems or abstractions
- **State over flow** — a single `WorkspaceState` drives everything; no phase machine
- **Agents are functions** — `expert_respond(state, agent_id, message) -> Message`, not `crew.kickoff()`
- **Events are flat** — same SSE event shapes in live and replay, same as current pattern
- **Delete first, build later** — old crew files stay on `main`, this branch writes new from scratch

## Phase 1: Data Model & Persistence

**Goal:** `WorkspaceState` + `WorkspaceDB` that can store and load panels, experts, knowledge pools, messages, and symposia.

**Files:**
- `src/council/workspace/__init__.py`
- `src/council/workspace/state.py` — `WorkspaceState`, `Panel`, `Expert`, `KnowledgePool`, `Message`, `Symposium`, `SourceEntry`, `Opinion`
- `src/council/workspace/db.py` — SQLite persistence, same pattern as current `db.py`

**Key decisions:**
- Panels own experts. Experts own knowledge pools. Symposia reference experts across panels.
- `Message` is the unified log — user messages, agent responses, system events. One table.
- No status field on the workspace itself — the state is derived from what exists, not a machine enum.

**Deliverable:** Tests that create a workspace, add a panel with experts, load it back.

## Phase 2: Agent Runtime

**Goal:** Invoke individual agents with workspace context. No CrewAI crew loops — just `agent -> message`.

**Files:**
- `src/council/workspace/agents.py` — thin wrappers: `expert_think(state, expert_id, prompt)`, `fact_check_source(state, source)`, `rapporteur_synthesize(state, symposium_id)`, `moderator_propose_panel(query, function_type)`
- `src/council/workspace/llm.py` — single helper: `ask_agent(agent_config, tools, prompt) -> str`

**Key decisions:**
- Each agent call is a standalone function with explicit inputs/outputs
- Tools are passed in explicitly, not registered globally
- Fact-Checker runs on individual sources, not the entire transcript at once
- No loops inside agent calls — the caller (CLI or server) controls iteration

**Deliverable:** Test that creates an expert, gives it a source, asks it a question, gets a structured response.

## Phase 3: API Layer

**Goal:** FastAPI endpoints for workspace operations. SSE streaming for agent responses and symposia.

**Files:**
- `src/council/workspace/server.py` — all workspace endpoints
- `src/council/workspace/sse.py` — SSE event emitter (reuses event shapes from current system)

**Endpoints:**
```
POST   /api/workspace                    — create workspace
GET    /api/workspace/{id}               — load workspace
POST   /api/workspace/{id}/panels        — create panel (moderator proposes)
PUT    /api/workspace/{id}/panels/{pid}  — edit panel
POST   /api/workspace/{id}/experts/{eid}/message  — send message to expert (SSE)
POST   /api/workspace/{id}/experts/{eid}/sources  — add source to expert
POST   /api/workspace/{id}/experts/{eid}/research — direct expert to search
POST   /api/workspace/{id}/symposia      — convene symposium
POST   /api/workspace/{id}/symposia/{sid}/message — send message in symposium (SSE)
POST   /api/workspace/{id}/export        — export dossier/memo
```

**Deliverable:** curl-based flow: create workspace → add panel → message expert → get response via SSE.

## Phase 4: GUI — Workspace Layout

**Goal:** Three-panel workspace view replacing the phase-based navigation.

**Files:**
- `gui/workspace.html` — new entry point
- `gui/workspace.js` — workspace logic
- `gui/workspace.css` — styles (reuses much of styles.css)

**Phased GUI rollout:**
1. **Panel builder** — create panel, see experts
2. **Expert conversation** — click expert, send message, see structured response
3. **Knowledge pool viewer** — see sources, upload files
4. **Symposium view** — convene debate, watch turns
5. **Context panel** — evidence scorecard, synthesis tabs

**Key decisions:**
- Keep the current Mission Control GUI working on `main` — workspace GUI is a new file set
- Reuse SSE event handlers where possible
- Vanilla JS, no framework — same as current

## Phase 5: Export & Polish

**Goal:** Decision memo, evidence graph, interactive briefing.

**Files:**
- `src/council/workspace/export.py` — dossier, memo, scorecard exporters

**Deliverable:** Export a dossier and a decision memo from a completed symposium.

---

## Shared Resources (used by all phases)

These are the `main` branch files that the workspace branch imports directly:

| File | Used as-is? | Notes |
|---|---|---|
| `agents/expert.py` | Yes | `build_expert_agent()` |
| `agents/moderator.py` | Yes | `build_moderator()` |
| `agents/fact_checker.py` | Yes | `build_fact_checker()` |
| `agents/rapporteur.py` | Yes | `build_rapporteur()` |
| `agents/dossier_author.py` | Yes | `build_dossier_author()` |
| `agents/expectation_*.py` | Yes | Both curator and evaluator |
| `tools/search_tool.py` | Yes | `create_search_tool()` |
| `tools/library_tool.py` | Yes | `create_library_tools()` |
| `tools/pdf_tool.py` | Yes | `create_pdf_tool()` |
| `config.py` | Yes | `build_llm()` |
| `config/agents.yaml` | Modified | Update backstories for workspace context |
| `config/tasks.yaml` | Modified | Remove pipeline-specific prompts, keep structured formats |

## What we never rebuild

- Crew files (`crews/`) — replaced by workspace agent calls
- `live_runner.py` — replaced by workspace SSE handler
- `simulator.py` — replaced by workspace replay
- `state.py` `CouncilState` — replaced by `WorkspaceState`
- `main.py` — replaced by workspace CLI
- `manifest.py` — replaced by workspace state persistence
