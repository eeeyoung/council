<p align="center">
  <h1 align="center">🏛️ SYMPOSIUM</h1>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License">
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/framework-crewAI-orange" alt="crewAI">
  <img src="https://img.shields.io/badge/vector%20store-ChromaDB-brightgreen" alt="ChromaDB">
</p>

<p align="center">
  <b>An AI-powered scientific symposium platform.</b><br>
  Convene a panel of AI scientists, each with a unique discipline and intellectual bias.<br>
  They research independently, debate in structured symposia, and produce fully-cited syntheses —<br>
  all grounded in a verifiable knowledge library.
</p>

---

## ✨ What is SYMPOSIUM?

SYMPOSIUM — *inspired by Plato's SYMPOSIUM* — is an interactive workspace where you assemble panels of AI experts, give them a research question, and watch them reason together. Each expert has a distinct discipline, personality, and intellectual leaning. They search for sources (verified against actual web pages, not search snippets), build a shared library of evidence, debate in structured symposia, and produce synthesized conclusions.

> *A self-contained AI research committee that never sleeps — and shows its work.*

---

## 🏛️ The Academy — Workspace GUI

The primary interface is a chat-centric three-panel workspace served at `http://localhost:8001`:

```
┌── Sidebar ───────────┬── Main Area ──────────┬── Context Panel ──┐
│ SYMPOSIUM            │ Expert name / sym     │ Library           │
│ Session · abc123     │   discipline · bias   │   Curated         │
│                      │                       │   Discovered      │
│ ▼ Panels          ✎  │ Conversation          │ Archive           │
│   ☉ Expert A         │   messages            │                   │
│   ☉ Expert B         │   structured debate   │                   │
│                      │                       │                   │
│ ▼ Symposia           │ Input Bar             │                   │
│   ⚡ Debate: ...      │                       │                   │
└──────────────────────┴───────────────────────┴───────────────────┘
```

**Expert chat** — talk one-on-one with any expert. They reason from their knowledge pool.

**Symposium debate** — convene multiple experts for structured debate. Each speaks in turn, citing evidence. The rapporteur synthesizes. Completed rounds are archived.

**Knowledge library** — every expert has a Curated (user-added) and Discovered (research-found) library. Sources are verified via full-page extraction, not search snippets.

---

## 🔬 Source Verification

The fact-checker verifies every source against the actual web page using **trafilatura** for content extraction. For open-access papers (arXiv, PLOS ONE, etc.), the full article body is extracted and the claimed quote is matched against it. PDFs are parsed directly. Paywalled sources are honestly marked as unverifiable rather than given false green checkmarks. Users can manually override any verification status.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (fast Python package manager)
- An LLM API key (DeepSeek, Gemini, or any OpenAI-compatible provider)

### Installation

```bash
git clone https://github.com/eeeyoung/council.git
cd council
uv sync
```

### Configuration

Edit `.env` with your API keys:

| Variable | Description |
|----------|-------------|
| `AI_PROVIDER` | `ds` for DeepSeek, `gem` for Gemini |
| `DEEPSEEK_API_KEY` | Your DeepSeek API key |
| `GEMINI_API_KEY` | Your Gemini API key |
| `TAVILY_API_KEY` | Tavily search API key (recommended — falls back to DuckDuckGo) |
| `MODEL` | Model identifier, e.g. `gemini/gemini-2.5-flash-lite` |

### Usage

#### Workspace GUI ("The Academy")

```bash
uv run python -m council.workspace.server --port 8001
```

Open `http://127.0.0.1:8001`. Create panels of experts, chat with them, research topics, convene symposia, and synthesize findings — all through the GUI.

#### Standalone Source Verifier

```bash
uv run python -m council.workspace.server --port 8001
# Then open http://localhost:8001/gui/verify.html
```

A test page where you input a claim + URL + quote and see a verification stamp (VERIFIED / MISATTRIBUTED / UNVERIFIABLE / UNCITED).

#### CLI — Legacy pipeline

```bash
uv run council "What are the most promising approaches to fusion energy?"
uv run python -m council.main "Is dark matter a WIMP or an axion?" --experts 5
```

#### Running tests

```bash
uv run pytest tests/ -v
```

---

## 📂 Project Structure

```
council/
├── config/
│   ├── agents.yaml              # Agent role, goal, and backstory definitions
│   └── tasks.yaml               # Task descriptions and expected output formats
├── gui/
│   ├── workspace.html           # The Academy — main workspace GUI
│   ├── workspace.js             # Workspace interactivity
│   ├── workspace.css            # Workspace styling
│   ├── verify.html              # Standalone source verifier page
│   ├── index.html               # Mission Control (legacy pipeline dashboard)
│   └── app.js                   # Mission Control interactivity
├── src/council/
│   ├── agents/
│   │   ├── expert.py            # Expert agent builder
│   │   ├── moderator.py         # Panel curator
│   │   ├── aggregator.py        # Research compiler
│   │   ├── rapporteur.py        # Synthesis author
│   │   ├── discussant.py        # Peer reviewer
│   │   ├── fact_checker.py      # Evidence scorecard
│   │   └── dossier_author.py    # Dossier compiler
│   ├── crews/
│   │   ├── research_crew.py     # Parallel research
│   │   ├── debate_crew.py       # Sequential debate
│   │   ├── audit_crew.py        # Audit loop
│   │   └── dossier_crew.py      # Final dossier
│   ├── tools/
│   │   ├── search_tool.py       # Web search (Tavily / DuckDuckGo)
│   │   ├── library_tool.py      # ChromaDB library + trafilatura verification
│   │   └── pdf_tool.py          # PDF content extraction
│   ├── workspace/
│   │   ├── agents.py            # Workspace agent functions
│   │   ├── server.py            # FastAPI server for The Academy
│   │   ├── state.py             # Session/expert/symposium data models
│   │   ├── db.py                # SQLite persistence
│   │   ├── sse.py               # Server-sent event streaming
│   │   ├── cli.py               # Workspace CLI
│   │   └── export.py            # Export module
│   ├── main.py                  # Legacy CLI entry point
│   ├── config.py                # Central config + env loader
│   └── state.py                 # Legacy pipeline state model
├── tests/                       # Test suite
├── pyproject.toml               # Project metadata + dependencies
└── README.md
```

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|------------|
| **Agent Framework** | CrewAI |
| **LLM Backend** | DeepSeek / Gemini / OpenAI-compatible |
| **Vector Store** | ChromaDB (persistent, per-expert collections) |
| **Web Search** | Tavily (primary), DuckDuckGo (fallback) |
| **Content Extraction** | trafilatura (HTML), pypdf (PDF) |
| **State Persistence** | SQLite (via Pydantic models) |
| **Frontend** | Vanilla JS, CSS custom properties, Times New Roman |
| **Package Manager** | uv |

---

## 📄 License

MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built with ❤️ using CrewAI, ChromaDB, and Python</sub>
</p>
