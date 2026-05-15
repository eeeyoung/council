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
src/council/db.py    — SQLite persistence for CouncilState (pause/resume)
src/council/config.py — Central config: build_llm(), provider keys, encoding fixes
gui/                 — Mission Control web dashboard (HTML/JS/CSS)
```

## Agents

| Agent | File | Temperature | Tools |
|---|---|---|---|
| Moderator | `agents/moderator.py` | 0.7 | web_search |
| Expert | `agents/expert.py` | 0.8 | web_search, library_read/write, pdf |
| Fact-Checker | `agents/fact_checker.py` | 0.2 | library_read, web_search |
| Rapporteur | `agents/rapporteur.py` | 0.4 | library_read |
| Discussant | `agents/discussant.py` | 0.2 | library_read |
| Expectation Curator | `agents/expectation_curator.py` | 0.4 | none |
| Expectation Evaluator | `agents/expectation_evaluator.py` | 0.2 | library_read |
| Aggregator | `agents/aggregator.py` | 0.4 | library_read |
| Dossier Author | `agents/dossier_author.py` | 0.6 | web_search |

## LLM & search config

- `build_llm(temperature)` in `config.py` — single source for LLM construction.
  Currently sets `timeout=120` to prevent hangs. Uses `AI_PROVIDER` env var
  (`ds` for DeepSeek, `gem` for Gemini). Model overridden via `MODEL` env var.
- Search backend controlled by `SEARCH_BACKEND` env var: `tavily`, `duckduckgo`,
  or `auto` (Tavily if key exists, else DuckDuckGo).
- DuckDuckGo uses the `ddgs` package (NOT the deprecated `duckduckgo_search`).
  Both `search_tool.py` and `library_tool.py` import `from ddgs import DDGS`.
- CrewAI deprecation warnings are suppressed in `config.py` via
  `warnings.filterwarnings("ignore", category=DeprecationWarning, module="crewai")`.

## Key patterns

- All agents extend `crewai.Agent` and read their config from YAML
- `CouncilState` is the central data model passed through all phases
- `transcript_text` renders debate entries with markers: `[Turn N]` for experts,
  `[RAPPORTEUR]`/`[DISCUSSANT]` for audit entries
- Live mode (SSE) emitter: `live_runner.py`. Review/replay emitter: `simulator.py`.
  Both must emit the same event shapes.
- Source verification happens inline at `library_write` — URLs/DOIs are validated
  before storage. Verification produces three tiers: verified, misattributed,
  unverifiable (never rejects outright).
- The Fact-Checker has both `library_read` and `web_search` tools
- `max_iter=8` on experts (room for search + writes + report)

## Server endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/sessions` | GET | List completed sessions (review mode) |
| `/api/sessions/{id}` | GET | Load session manifest |
| `/api/sessions/generate-panel` | POST | Run Moderator → return panel (no curator) |
| `/api/sessions/{id}/proceed` | POST | Save edited panel, run Expectation Curator |
| `/api/sessions/{id}/live` | GET | SSE stream — runs full live pipeline |
| `/api/config` | GET | Return server mode (`live` or `review`) |
| `/outputs/{filename}` | GET | Serve output files (transcripts, dossiers, etc.) |

## Workspace GUI architecture

`gui/workspace.js` + `gui/workspace.html` — "The Academy" (served by `council.workspace.server`).
A chat-centric workspace with a different model from Mission Control. Served at `/` via
`workspace.html`. Run with:

```bash
uv run python -m council.workspace.server --port 8001
```

### Three-panel layout

```
┌── Sidebar ───────────────┬── Main Area ──────────────────┬── Context Panel ──┐
│ COUNCIL                  │ Header (expert name / sym)     │ [Evidence]        │
│ Session · abc123         │   discipline · meta  [actions] │ [Sources]         │
│                          │                                │ [Synthesis]       │
│ ▼ Panels                 │ Conversation                   │                   │
│   ☉ Expert A             │   messages / empty state       │ context-content   │
│   ☉ Expert B             │   typing indicator             │                   │
│   [+ New Panel]          │                                │                   │
│                          │ Input Bar (expert chat only)   │                   │
│ ▼ Symposia               │   [text input] [Send] [Stop]  │                   │
│   ⚡ Debate: ...          │                                │                   │
│                          │                                │                   │
│ [← Workspaces]           │                                │                   │
└──────────────────────────┴────────────────────────────────┴───────────────────┘
```

### UI region glossary

| Region | DOM anchor | What it contains |
|--------|-----------|-----------------|
| **Sidebar** | `#sidebar` | Session name, **Panel List** (`#sidebar-panels`), **Symposia List** (`#sidebar-symposia`), Workspaces button |
| **Main Area** | `#main-panel` | Contains `#main-content` (header + conversation) and `#input-bar` |
| **Header** | `.main-header` inside `#main-content` | Expert/symposium name, discipline, action buttons |
| **Conversation** | `#conversation` inside `#main-content` | Message bubbles, empty state, typing indicator |
| **Input Bar** | `#input-bar` | Text input + Send + Stop (visible only for Expert Chat) |
| **Context Panel** | `#context-panel` | Evidence / Sources / Synthesis tabs (`#context-content`) |
| **Modal** | `#modal-overlay` | Overlay for create session, add experts, convene symposium, add source, upload |
| **Toast** | `#toasts` | Corner notifications |

### Views (what appears in the Main Area)

| View | Trigger | Header shows | Input bar |
|------|---------|-------------|-----------|
| **Session List** | `showSessionList()` / "← Workspaces" | "The Academy" + session cards | hidden |
| **Expert Chat** | Click expert in Panel List | Expert name, discipline, bias; [ + Source ] [ ☰ Context ] | visible |
| **Symposium** | Click symposium in Symposia List, or after creation | ⚡ title, format, N experts, N msgs; [ ▶ Run Round ] [ 📋 Synthesize ] | hidden |

### Key globals

| Variable | Purpose |
|----------|---------|
| `_sessionId` | Current session UUID |
| `_session` | Full session JSON from `GET /api/sessions/{id}` |
| `_activeExpert` | Currently selected expert object (null when viewing symposium/list) |
| `_activeSymposium` | Currently selected symposium ID (null when viewing expert/list) |
| `_symposiumMessages` | `{symposiumId: [{role, name, content, turn, accent}]}` — persisted to `sessionStorage` |
| `_symposiumTyping` | `{symposiumId: {name, discipline}}` — current speaker, also persisted |
| `_expertAvatars` | `{expertId: avatarDef}` — generated avatars |
| `_expertAccents` | `{expertId: colorClass}` — accent colors |

### Critical rules for workspace.js

- **Symposium messages and typing state MUST be stored in `_symposiumMessages` /
  `_symposiumTyping`, not just the DOM.** When the user navigates away (clicks an
  expert), `selectExpert()` destroys the `#main-content` DOM entirely. On return,
  `_renderSymposiumView()` rebuilds everything from the persistent stores.
- **Capture symposium ID locally in SSE callbacks.** Use `const symId = _activeSymposium`
  before any `await`. `_activeSymposium` gets set to `null` by `selectExpert()`, so
  callbacks that reference it directly will write to `_symposiumMessages[null]`.
- **Call `_persistSymState()` after every mutation** to `_symposiumMessages` or
  `_symposiumTyping` so state survives page refreshes.
- **Use session data, not create response, for `_renderSymposiumView()`.** The
  POST `/api/sessions/{id}/symposia` response only has `{symposium_id, participants}`.
  Call `refreshSessionData()` then look up the full symposium from `_session.symposia`.
- **Call `renderSidebar()` + `renderSymposiaList()` after creating a symposium**
  so it appears in the sidebar without a page refresh.

### Workspace server endpoints (`council.workspace.server`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/sessions` | GET | List all sessions |
| `/api/sessions` | POST | Create a new session |
| `/api/sessions/{id}` | GET | Get full session (experts, symposia, messages) |
| `/api/sessions/{id}/panels` | POST | Moderator proposes experts for a query |
| `/api/sessions/{id}/experts/{eid}/message` | POST | SSE — chat with an expert |
| `/api/sessions/{id}/experts/{eid}/pool` | GET | Get expert's knowledge pool |
| `/api/sessions/{id}/experts/{eid}/sources` | POST | Add source to expert's pool |
| `/api/sessions/{id}/experts/{eid}/upload` | POST | Upload file to expert's pool |
| `/api/sessions/{id}/experts/{eid}/opinion` | POST | SSE — form expert opinion |
| `/api/sessions/{id}/symposia` | POST | Create a symposium |
| `/api/sessions/{id}/symposia/{sid}/round` | POST | SSE — run a debate round |
| `/api/sessions/{id}/symposia/{sid}/synthesize` | POST | SSE — synthesize symposium |

## Mission Control GUI architecture (`app.js`)

`gui/app.js` + `gui/index.html` — "Mission Control" (served by `council.server`).
A 5-phase pipeline dashboard with live SSE and review modes. Run with:

```bash
uv run python -m council.server               # review mode
uv run python -m council.server --mode live   # live mode
```

### Key globals

| Variable | Purpose |
|---|---|
| `currentSession` | Manifest object (truthy when session loaded) |
| `_liveSSE` | EventSource instance (truthy when pipeline running) |
| `panelWizardState` | Phase A wizard state (step, query, experts, etc.) |
| `_liveDebateMessages` | Accumulated debate/audit messages from SSE |
| `_liveDossier` | Accumulated dossier text during streaming |

**Phase switching** — `switchPhase(phaseId)` sets nav active, renders spinner,
then calls `render<Phase>Phase()`. Each render function checks `_liveSSE`:
if truthy, renders from live data stores; if falsy, reads from session files.

**SSE event flow** — `_connectLiveSSE(sessionId)` opens EventSource and registers
handlers for: `session_start`, `phase_start`, `research_status`, `research_start`,
`research_complete`, `phase_complete`, `round_start`, `debate_typing`,
`debate_message`, `scorecard_ready`, `audit_result`, `expectation_result`,
`dossier_chunk`, `session_complete`.

**Critical rule for SSE handlers:** When an SSE handler modifies the DOM of a
specific phase, it MUST check that the user is still viewing that phase before
mutating DOM. Pattern:
```javascript
const activeBtn = document.querySelector('.nav-btn.active');
if (activeBtn && activeBtn.dataset.phase === 'expected-phase') { /* mutate */ }
```

### Phase animations

Each phase has a waiting-state animation that runs via `setInterval` during
blocking API calls. All timers are cleared in `switchPhase()` before navigating.

| Phase | Animation | Timer var | Key function |
|---|---|---|---|
| A | Council Table — names shuffle through chairs | `_deliberationTimer` | `_startCouncilDeliberation()` → `_settleCouncilTable()` |
| B1 | Library Shelves — books slide onto shelves | `_shelvesTimer` | `_renderLibraryShelves()` |
| B2 | Stamp Verification — ✓/✗ on conveyor belt | `_stampTimer` | `_renderStampVerification()` |
| B3 | Thought Bubbles — pulsing bubbles above experts | `_bubbleTimer` | `_renderThoughtBubbles()` |
| C | Podium Spotlight — active speaker rises/glows | (CSS transition) | `_renderPodium()` / `_updatePodium()` |
| D | Courtroom Drama — Rapporteur vs Discussant, gavel | `_courtroomTimer` | `_renderCourtroom()` / `_courtroomShowVerdict()` |

**Animation patterns:**
- `_deliberationInProgress` flag prevents Phase A from resetting to the query form
  when navigating away and back during panel generation
- `_settleCouncilTable()` uses `[class*="council-slot-"]` selector (NOT `\d+` —
  regex is invalid CSS and throws SyntaxError)
- All timers are null-checked before `clearInterval` in `switchPhase()` and
  `startNewSession()`

## Expectation system

Phase A lets users define a desired outcome type (definitive answer, feasible plan,
balanced overview, research roadmap, decision analysis, hypothesis evaluation, custom).

- **Expectation Curator** — runs in `proceed` endpoint. Translates the user's outcome
  type + detail into concrete success criteria stored in `state.expectation_criteria`.
- **Expectation Evaluator** — runs in Phase D after Discussant approves. Checks
  whether the final synthesis meets the criteria. Sets `state.expectation_met`.

## When adding a new agent

1. Add entry to `config/agents.yaml` (role, goal, backstory)
2. Add task(s) to `config/tasks.yaml`
3. Create agent file in `src/council/agents/` with `build_<name>()` function
4. Use the agent in the appropriate crew file
5. Update `README.md` agent table and project structure
6. Update this file's agent table

## When changing the pipeline

- `main.py` — CLI path (synchronous)
- `live_runner.py` — Live mode SSE path (async generator wrapping sync calls)
- `simulator.py` — Review/replay SSE path (reads files, no LLM)
- `state.py` — `CouncilState.status` drives the phase transitions
- All three paths (CLI, live, replay) should produce semantically equivalent
  output files and manifest entries

## When adding/updating an SSE event

- `live_runner.py` — yield the event
- `simulator.py` — yield matching event (same shape) for review replay
- `gui/app.js` — add listener in `_connectLiveSSE()`
- New events must use the same JSON shape in both live and simulator paths

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
- Phase D `phase_start` event is emitted from inside Phase C's loop when
  `state.status == "auditing"` — not as a separate top-level phase transition
- `Expectation Curator` runs in `proceed` endpoint, not `generate-panel`, so the
  panel response returns immediately to the GUI
- DuckDuckGo import is `from ddgs import DDGS` in BOTH `search_tool.py` AND
  `library_tool.py` (the latter does quote verification)
