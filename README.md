<p align="center">
  <h1 align="center">🏛️ COUNCIL</h1>
  <p align="center">
    <strong>Collaborative Open-source Unified Consortium for Industrial & Logical Research</strong>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License">
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/framework-crewAI-orange" alt="crewAI">
  <img src="https://img.shields.io/badge/vector%20store-ChromaDB-brightgreen" alt="ChromaDB">
</p>

<p align="center">
  <b>An AI-powered scientific brainstorming framework.</b><br>
  Convene a panel of AI scientists, have them research and debate any question,<br>
  subject the results to adversarial peer review, and produce a fully-cited dossier — automatically.
</p>

---

## ✨ What is COUNCIL?

COUNCIL simulates an entire scientific symposium using multiple AI agents. You provide a research question — the system assembles a curated panel of experts, each with a unique discipline, personality, and intellectual bias. Those experts independently research the topic, debate it in a structured forum, and then face a hostile peer-review audit. The output is a publication-ready dossier with full citations.

> *Think of it as a self-contained AI research committee that never sleeps.*

---

## 🧠 Architecture

COUNCIL runs a five-phase pipeline — each phase feeds into the next:

| Phase | Name | What Happens |
|:-----:|------|--------------|
| **A** | Panel Curation | Moderator Agent analyzes the query and proposes a panel of expert personas. You interactively approve, regenerate, or edit the panel. |
| **B** | Parallel Research | Each expert independently searches the web and writes findings into a shared ChromaDB vector library. All experts run in parallel. An aggregator compiles structured summaries. |
| **C** | Sequential Symposium | Experts speak in turn order, responding to peers and citing evidence. The Recorder Agent maps every claim to a citation (Evidence Scorecard). |
| **D** | The Audit Loop | Host A synthesizes a Unified Hypothesis. Host B performs a hostile peer review and returns APPROVED or REJECTED. If rejected, the system loops back to Phase C with a conflict mandate (up to 3 rounds). |
| **E** | Final Dossier | The Recorder compiles everything into a publication-ready Markdown dossier with full bibliography and claim-to-citation mappings. |

```
   PHASE A ──► PHASE B ──► PHASE C ──► PHASE D ──► PHASE E
 (Curate)    (Research)   (Debate)    (Audit)     (Dossier)
                                ▲          │
                                └─ REJECT ─┘
```


---

## 🎭 Agent Types

| Agent | Role |
|-------|------|
| **Moderator** | Analyzes the query and assembles the optimal panel of expert personas |
| **Expert** (×N) | Each researches, debates, and writes — with a unique discipline, bias, and persona |
| **Recorder** | Maps every factual claim to a source citation; compiles the final dossier |
| **Host A** (Synthesis) | Distills the full debate transcript into a unified hypothesis |
| **Host B** (Hostile Peer) | Adversarially audits the synthesis for lazy consensus, logical errors, and unsupported claims |
| **Aggregator** | Compiles all parallel research into structured summaries |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (fast Python package manager)
- An LLM API key (DeepSeek, Gemini, or any OpenAI-compatible provider)

### Installation

```bash
# Clone the repository
git clone https://github.com/eeeyoung/council.git
cd council

# Install dependencies
uv sync
```

### Configuration


Edit `.env` with your API keys:

| Variable | Description |
|----------|-------------|
| `AI_PROVIDER` | `ds` for DeepSeek, `gem` for Gemini |
| `DEEPSEEK_API_KEY` | Your DeepSeek API key |
| `GEMINI_API_KEY` | Your Gemini API key |
| `TAVILY_API_KEY` | (Optional) Tavily search key — falls back to DuckDuckGo |
| `MODEL` | Model identifier, e.g. `gemini/gemini-2.5-flash-lite` |

### Run Your First Symposium

```bash
# Basic usage
uv run python -m council.main "What are the most promising approaches to fusion energy?"

# Customize the expert panel size
uv run python -m council.main "Is dark matter a WIMP or an axion?" --experts 3

# Skip interactive panel approval (good for CI / testing)
uv run python -m council.main "Your question" --no-confirm

# Resume a previous session
uv run python -m council.main --session-id abc12345

# Enable verbose logging to see agents' thought process
uv run python -m council.main "Your question" --verbose
```

---

## 📂 Project Structure

```
council/
├── config/
│   ├── agents.yaml          # Agent role, goal, and backstory definitions
│   └── tasks.yaml           # Task descriptions and expected output formats
├── gui/
│   ├── index.html           # Mission Control web dashboard
│   ├── app.js               # Dashboard interactivity
│   └── styles.css           # Dashboard styling
├── src/council/
│   ├── agents/
│   │   ├── expert.py        # Expert agent builder (research + debate)
│   │   ├── moderator.py     # Panel curation (Phase A)
│   │   ├── host_a.py        # Synthesis host (Phase D)
│   │   ├── host_b.py        # Hostile peer reviewer (Phase D)
│   │   └── recorder.py      # Evidence scorecard + dossier (Phases C, E)
│   ├── crews/
│   │   ├── research_crew.py # Parallel research crew (Phase B)
│   │   ├── debate_crew.py   # Sequential debate crew (Phase C)
│   │   ├── audit_crew.py    # Audit loop (Phase D)
│   │   └── dossier_crew.py  # Final dossier (Phase E)
│   ├── tools/
│   │   ├── search_tool.py   # Web search (Tavily / DuckDuckGo)
│   │   ├── library_tool.py  # ChromaDB-backed shared research library
│   │   └── pdf_tool.py      # PDF content extraction
│   ├── main.py              # CLI entry point
│   ├── config.py            # Central config + env loader
│   ├── state.py             # Pydantic state model (SQLite-persistable)
│   └── db.py                # SQLite state persistence
├── tests/                   # Test suite
├── .env.example             # Environment variable template
├── pyproject.toml           # Project metadata + dependencies
└── README.md
```


---

## 🔬 Example Output

After running a symposium on *"Is dark matter a WIMP or an axion?"*:

| File | Contents |
|------|----------|
| `*_research_dr_elena_vasquez.md` | Expert research summary (5 cited findings) |
| `*_transcript.md` | Structured debate transcript with peer responses |
| `*_scorecard.md` | Evidence scorecard mapping claims to sources |
| `*_dossier.md` | Final publication-ready dossier with full bibliography |

Sample debate excerpt:

> **[Dr. Elena Vasquez]:** A froth image is not merely a statistical texture — it is a snapshot of a dynamic thin-film network governed by well-understood physical chemistry. The bubble size distribution you see is a direct consequence of coalescence inhibition...
>
> **[Dr. Kenji Tanaka]:** I agree with her core premise. However, I must challenge the execution strategy. The bottleneck should instead be a learned, differentiable latent space. Physics-informed latent diffusion models reduce prediction errors by 65%...

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|------------|
| **Agent Framework** | [CrewAI](https://crewai.com) v0.100+ |
| **LLM Backend** | DeepSeek / Gemini / OpenAI-compatible |
| **Vector Store** | ChromaDB (persistent) |
| **Web Search** | Tavily |
| **State Persistence** | SQLite (via Pydantic models) |
| **CLI** | Rich (beautiful terminal UI) |
| **Embeddings** | Google Generative AI embeddings |
| **Package Manager** | uv |

---

## 🧪 Running Tests

```bash
uv run pytest tests/ -v
```

---

## 🤝 Contributing

Contributions are welcome! Areas of interest include:

- New agent types (domain-specific experts)
- Additional LLM backends (Ollama, Anthropic, OpenAI)
- Improved GUI dashboard features
- Better evaluation metrics for synthesis quality
- Multi-language support

Please open an issue or PR on the repository.

---

## 📄 License

MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built with ❤️ using CrewAI, ChromaDB, and Python</sub>
</p>