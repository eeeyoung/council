# Contributing to COUNCIL

Thank you for your interest in contributing. COUNCIL is a multi-agent scientific
brainstorming framework built on CrewAI and ChromaDB. This guide covers
everything you need to make a successful contribution.

## Code of Conduct

- Be constructive in discussions
- Focus on evidence and clear reasoning (like the agents themselves)
- Respect review feedback — it makes the work stronger

## Development Setup

```bash
# Prerequisites: Python 3.12+, uv
git clone https://github.com/eeeyoung/council.git
cd council

# Install dependencies
uv sync

# Copy and fill in API keys
cp .env.example .env
# Edit .env with your LLM and search keys
```

### Running tests

```bash
uv run pytest tests/ -v
```

All PRs must pass the existing test suite. Add tests for new functionality.

### Running the project

```bash
# CLI symposium
uv run council "Your research question"

# Web server (review mode — browse past sessions)
uv run python -m council.server

# Web server (live mode — run new sessions via GUI)
uv run python -m council.server --mode live
```

## Code Style

- Python: follow PEP 8
- JavaScript/CSS: in `gui/`, use 4-space indentation, consistent with existing code
- Agent configurations: all agents go in `config/agents.yaml`, tasks in `config/tasks.yaml`
- Agent implementations: one agent per file in `src/council/agents/`
- Use `uv run` for all commands
- No comments unless the WHY is non-obvious

## Architecture Notes

```
config/          Agent and task definitions (YAML) — edit here for prompt changes
src/council/
  agents/        One file per agent — thin wrappers reading from YAML config
  crews/         Phase implementations (research, debate, audit, dossier)
  tools/         Tool implementations (search, library, PDF)
  manifest.py    Shared manifest writer (one source of truth)
gui/             Mission Control web dashboard
```

- Each agent reads its role/goal/backstory from `config/agents.yaml`
- Each task reads its description from `config/tasks.yaml`
- The `CouncilState` Pydantic model is the single data structure through the pipeline
- ChromaDB stores research findings per session

## Contribution Workflow

### 1. Find or create an issue

All changes start with an issue. Use the Bug Report or Feature Request template.

### 2. Fork and branch

```bash
# Use a descriptive branch name
git checkout -b feature/add-temperature-control
git checkout -b fix/research-output-extraction
```

### 3. Make your changes

- Keep PRs focused — one concern per PR
- Add tests for new behavior
- Update `README.md` if adding new features or changing the CLI
- Run `uv run pytest tests/ -v` before pushing

### 4. Open a Pull Request

Use the PR template. Your PR must include:

- **Summary**: What changed and why (1-3 bullet points)
- **Test plan**: How you tested the changes (a checklist)
- **Screenshots**: If the change affects the GUI, include before/after screenshots

### 5. Review

All PRs require review before merging. The review checks for:

- Correctness — does the change do what it claims?
- Test coverage — are there tests for the new behavior?
- Consistency — does it follow existing patterns in the codebase?
- Config — are new agents/tasks properly in the YAML configs?
- No regression — do all existing tests still pass?

The reviewer may request changes. This is normal — it makes the work stronger.

### 6. Merge

Once approved, the PR is squashed and merged. The commit message should follow
the repo style: a short imperative summary (e.g., "Add temperature control to
expert agents").

## What Makes a Good PR

- **One concern**: Don't mix bug fixes with new features
- **Small**: Prefer smaller PRs over large ones — they're easier to review
- **Tested**: Include tests that verify your change
- **Documented**: Update the README if user-facing behavior changes
- **Clean**: Remove debug code, commented-out blocks, and unnecessary comments

## Where to Get Help

- Check existing issues for similar problems or discussions
- Read the architecture section above to understand how the codebase is organized
- Look at the existing agent implementations in `src/council/agents/` for patterns
