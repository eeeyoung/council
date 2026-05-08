# COUNCIL — Design Document

## Summary

COUNCIL is evolving from a linear 5-phase pipeline into a **multi-panel knowledge workspace** where users assemble expert panels, feed them evidence, direct their research, convene debates, and produce auditable, decision-grade conclusions.

The core shift: **from running an AI pipeline to working inside an advisory committee.**

---

## Architecture

### Modules (replacing the 5-phase pipeline)

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  PANEL BUILDER  │ ──▶ │ EXPERT DASHBOARDS │ ──▶ │    SYMPOSIUM     │
│  (entry point)  │     │ (knowledge pools) │     │   (debate/audit) │
└─────────────────┘     └──────────────────┘     └──────────────────┘
                                                          │
                                                          ▼
                                                 ┌──────────────────┐
                                                 │     EXPORT       │
                                                 │ (dossier/memo)   │
                                                 └──────────────────┘
```

Phases are no longer vertically connected. Each module is independent and user-invoked.

---

### 1. Panel Builder (Entry Point)

Two modes, user picks at start:

**Mode A — Research Question Oriented**
1. User enters a research question
2. AI (Moderator) proposes an expert panel with disciplines, biases, and personas
3. User edits, adds, removes, reorders experts
4. Panel is created and experts are initialized

**Mode B — Function Oriented**
1. User states what they need: "Feasibility assessment of solid-state battery manufacturing" or "Technology due diligence on quantum computing startups"
2. AI proposes the disciplines and expert profiles needed for that function
3. User customizes
4. Panel is created

A user can have **multiple panels**. Panels are persistent and reusable.

---

### 2. Expert Dashboards

Each expert has their own dashboard. The user can:

1. **Edit profile** — name, photo/avatar, discipline, bias, persona prompt
2. **Upload data** — PDF, DOC, CSV, images. Parsed and added to the expert's knowledge pool
3. **Add verified URLs** — the user can paste URLs directly with context
4. **Direct research** — "Search for recent papers on X and collect findings." The expert uses web search (and future academic DB integration) to find sources. Results go through Fact-Checker gate before entering the knowledge pool.
5. **Form opinions** — "Based on your verified sources, what's your position on Y?" The expert synthesizes from their pool. All claims must cite pool sources.
6. **Review the pool** — See all sources, verification statuses, and opinions. Remove or annotate entries.

**Knowledge pool structure:**
```
Expert: Socratyes
├── [uploaded]  climate_data.pdf
├── [uploaded]  ipcc_report_section.doc
├── [collected] 5 URLs found via search
├── [verified]   3 URLs passed Fact-Checker gate
├── [rejected]   1 URL fabricated or inaccessible
└── [opinions]   "Carbon tax outperforms cap-and-trade in..."
                  └── cites: ipcc_report_section.doc, verified URL #2
```

Steps 4 and 5 (research and opinion formation) are **Fact-Checker gated** — the expert cannot form an opinion citing an unverified source and cannot cite a source not in their pool.

---

### 3. Symposium

A debate convened by the user. Can happen:

- **Within a panel** — the panel's experts debate its research question
- **Cross-panel** — experts from different panels debate a new topic
- **Any subset** — the user picks which experts participate

**Formats:**
- **Structured turn-based** — like current Phase C. Sequential turns, Fact-Checker scorecard after each round. Best for formal evaluation.
- **Free discussion** — all experts respond to the topic. User moderates. Best for exploration.
- **1:1 deep dive** — user and a single expert. Best for understanding that expert's position.

**During a symposium:**
- Fact-Checker monitors all claims in real-time, scorecard builds live
- User can interrupt, redirect, @mention specific experts
- User can pause to rule on disputed claims (see "User as Judge" in Extensions)
- When satisfied, user ends the symposium and can export

---

### 4. Export

Available at any time, not just at the end:
- **Evidence scorecard** — all claims, sources, verification statuses
- **Symposium transcript** — full debate record
- **Decision memo** — structured recommendation with scored options
- **Full dossier** — comprehensive document (current Phase E format)

---

## Data Model

```
User
├── Workspace
│   ├── Panel: "Climate Economics"
│   │   ├── Expert: Socratyes
│   │   │   ├── profile: {name, photo, discipline, bias, persona}
│   │   │   └── knowledge_pool:
│   │   │       ├── sources: [uploaded, collected, verified, rejected]
│   │   │       └── opinions: [claims with source citations]
│   │   │
│   │   ├── Expert: Kantwell
│   │   │   └── knowledge_pool: ...
│   │   │
│   │   └── Symposia:
│   │       └── "Carbon pricing mechanisms"
│   │           ├── participants: [Socratyes, Kantwell]
│   │           ├── transcript: [...]
│   │           └── scorecard: [...]
│   │
│   ├── Panel: "AI Safety Policy"
│   │   ├── Expert: Hypatienne
│   │   ├── Expert: Arendelle
│   │   └── Symposia: ...
│   │
│   └── Cross-Panel Symposia:
│       └── "Economic impacts of AI regulation"
│           ├── participants: [Socratyes (Climate Econ), Arendelle (AI Safety)]
│           └── ...
```

---

## Agent Roles (revised)

| Agent | Role | When invoked |
|---|---|---|
| **Moderator** | Proposes expert panels from query or function | Panel Builder |
| **Expert** | Builds knowledge pool from user uploads + directed research. Forms opinions from pool only. Debates in symposia. | Dashboard + Symposium |
| **Fact-Checker** | Continuous — verifies every source entering any knowledge pool. Monitors all claims during symposia. Produces scorecard. | Dashboard + Symposium |
| **Rapporteur** | Synthesizes debate into consensus map, disagreement landscape, and unified hypothesis. Invoked by user when ready. | Symposium (user-invoked) |
| **Expectation Evaluator** | Checks synthesis against user's desired outcome criteria. | Symposium (user-invoked) |
| **Dossier Author** | Compiles final dossier or decision memo. | Export |
| ~~Discussant~~ | Removed | — |

---

## Structured Output Formats

### Expert Debate Turn
```
## Position
[1-3 sentence core thesis.]

**Keywords:** [3-5 comma-separated key terms]

## Response to Peers
### To {Expert Name}
[Substantive response — support with evidence or challenge.]

## Evidence
### {Finding Short Title}
**Claim:** [The specific factual claim.]
**Source:** [URL or DOI.]
**Quote:** [The exact sentence from the source.]
```
- `claim_type` distinguishes: **empirical** (from Evidence, citeable), **inference** (from Response to Peers, reasoning), **position** (from Position, thesis)
- GUI renders each section with distinct visual hierarchy

### Rapporteur Synthesis
```
## Consensus Map
### {Consensus Point Title}
**Strength:** [Strong / Moderate / Weak]
**Held by:** {Expert Name}, {Expert Name}
**Evidence:** [Reference to scorecard evidence.]

## Disagreement Landscape
### {Disagreement Point Title}
**Positions:** {A} argues [X], {B} contends [Y].
**Evidence gap:** [What would resolve this.]
**Significance:** [Critical / Moderate / Minor]

## Unified Hypothesis
[2-4 sentence synthesized conclusion.]

**Keywords:** [3-5 synthesis-level terms]
```

### Fact-Checker Scorecard
JSON array. Each entry:
```json
{
  "claim": "...",
  "agent_name": "...",
  "claim_type": "empirical | inference | position",
  "source_url": "...",
  "verification_status": "verified | misattributed | unverifiable | no_source",
  "source_quote": "...",
  "relevance_note": "..."
}
```
- Non-empirical claims get neutral badges in GUI ("Expert reasoning", "Thesis statement"), not warnings
- Only `misattributed` gets an amber alert badge

---

## GUI: Three-Panel Workspace Layout

```
┌──────────────────┬──────────────────────────────┬──────────────────────┐
│   AGENT ROSTER   │       CONVERSATION           │    CONTEXT PANEL     │
│                  │                              │                       │
│  ● Socratyes     │  [Socratyes]: ## Position    │  [Evidence][Sources] │
│    (speaking)    │  The causal link between...   │  [Synthesis]         │
│                  │                              │                       │
│  ○ Kantwell      │  **Keywords:** causal         │  Evidence scorecard   │
│                  │  inference, confounding       │  grid with filters    │
│  ○ Hypatienne    │                              │  and verification     │
│                  │  ## Evidence                 │  badges. Updates in   │
│  ○ Foulcavie     │  ### Primary Finding         │  real-time.           │
│                  │  **Claim:** ...               │                       │
│  [+ Add Agent]   │                              │                       │
│                  │                              │                       │
├──────────────────┴──────────────────────────────┴──────────────────────┤
│  @mention an agent or /command...                                [Send] │
└────────────────────────────────────────────────────────────────────────┘
```

**Left — Agent Roster:** Status dots (idle/thinking/speaking). Click for profile and knowledge pool. Add/remove agents.

**Center — Conversation:** All messages (user, agent, system). Agent messages use structured format. Markdown rendered with visual hierarchy.

**Right — Context Panel:** Tabbed — Evidence scorecard, Source pool, Synthesis document.

**Input Bar:** Free text with @mentions. Slash commands: `/search`, `/verify`, `/synthesize`, `/dossier`, `/add`, `/debate`.

---

## Why This Is Differentiated

### Commodity (what everyone has)
- LLM with web search
- LLM with file upload / RAG
- Fact-checking via URL verification
- AI debate transcripts

### Differentiated (what COUNCIL uniquely provides)

| Feature | Why it matters | Why someone pays |
|---|---|---|
| **Persistent knowledge pools per expert** | Experts develop coherent intellectual identities. Opinions grounded in specific, auditable sources — not the entire internet. | Hold experts accountable. "Why do you believe X?" → "Because of source Y in my pool." |
| **Cross-panel symposia** | Bring experts from different domains together on new questions. | The interesting questions live between disciplines. No single chatbot does this well. |
| **User as knowledge contributor** | Upload PDFs, add URLs, direct research. Expert reasons on the user's evidence, not just public web. | The user has domain knowledge the AI doesn't — internal reports, proprietary data. |
| **Auditable chain from source to conclusion** | Every claim → source → verification status → opinion → debate position → consensus → conclusion. Full provenance. | In high-stakes decisions, being able to trace "why" is more valuable than the answer itself. |
| **Disagreement as a feature** | Maps who believes what, why, and what evidence would settle it. | Knowing what the panel disagrees on is more useful than a confident but wrong single answer. |

### The pitch

> **COUNCIL is not an AI that answers your question. It's a room of scientists you assemble, feed your evidence, and debate with — until you're confident in the conclusion.**

The competitor isn't ChatGPT or Perplexity. It's the advisory committee you can't afford to convene.

---

## Extensions (Future)

Ideas that deepen the methodology but are deferred from initial implementation.

### E1: From Dossier to Decision Memo
The output should be a **scored recommendation**, not just a research document:
- Options scored against explicit criteria
- Confidence levels per option
- Dissenting views flagged and attributed
- Evidence gaps mapped

The user asks "Should we invest in A or B?" and gets back a decision, not a summary.

### E2: User as Judge
During a symposium, when experts deadlock on a disputed claim, the user adjudicates:
> *"Kantwell claims X. Socratyes says the study is unreliable. Do you accept this claim into the evidence record, or strike it?"*

The user's rulings shape what enters the synthesis. The Fact-Checker flags, but the user decides. This makes the experience **exercising judgment with AI support**, not watching AI talk.

### E3: Evolving Evidence
Knowledge pools aren't static. When new papers or data emerge, opinions can be re-evaluated:
> *"A new RCT was published that contradicts Kantwell's position. Re-open the symposium?"*

Transforms the workspace into a **living advisory body** — a panel that stays current as evidence evolves.

### E4: Interrogable Conclusions
Instead of a static dossier, the output is an **interactive briefing**:
- Click any conclusion → see the full evidence chain
- Click a dissenting expert → see their argument with support
- Click a claim → see source quote and verification status
- Shareable web view — stakeholders interrogate the conclusion without reading the full debate

This is how real briefings work: the principal questions the analyst, not the report.

### E5: Integration with Research Infrastructure
Web search is the shallowest source layer. Deeper integrations:
- **Academic databases:** arXiv, PubMed, Semantic Scholar, Web of Science
- **Regulatory/legal:** SEC EDGAR, FDA filings, patent databases (USPTO, Espacenet)
- **Structured data:** clinical trial registries, materials property databases, economic indicators
- **Proprietary user data:** the PDFs, spreadsheets, and internal reports the user uploads

### E6: Auditable Reasoning Graph
The full provenance system:

```
Conclusion: Option A is recommended (confidence: 78%)

├── Supporting claim #1: "Cost reduction of 40% by 2030"
│   ├── Source: DOE report 2025, page 34 ✓ verified
│   ├── Opinion: Socratyes (+3 others agree)
│   └── Dissent: Kantwell — "assumes manufacturing scale not yet demonstrated"

├── Supporting claim #2: "Supply chain risks manageable"
│   ├── Source: McKinsey analysis 2025 ✓ verified
│   ├── Opinion: Hypatienne (+2 others agree)
│   └── Dissent: none

├── Opposing claim: "Alternative B has longer track record"
│   ├── Source: Industry consortium data 2019-2025 ✓ verified
│   ├── Opinion: Kantwell (sole advocate)
│   └── Rebuttal: Socratyes — "track record in a different application context"

└── Evidence gap: "No long-term durability data"
    └── All 5 experts flag this as critical unknown
```

Every conclusion has a paper trail. Every claim has a source. Every source has verification. Every opinion has a name. This is the **structural moat** — no single-LLM product can fake provenance.

### E7: Workflow Composer
Users compose their own workflow from agent building blocks:
- "3 experts, no audit, raw transcript only"
- "6 experts, 2 debate rounds, Fact-Checker after each round, no synthesis"
- Drag agents onto a canvas, wire them together

The 5-phase pipeline is a default preset, not the only way.

### E8: Multi-Panel Management
A user can have multiple panels for different domains. Panels are persistent. Experts can be shared across panels. Symposia can be convened within or across panels.
