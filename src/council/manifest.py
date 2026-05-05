"""
council/manifest.py

Shared manifest writer — writes outputs/{session_id}_manifest.json for GUI
consumption. Used by the CLI (main.py), live runner (live_runner.py), and
server (server.py) so there is a single source of truth for the manifest format.
"""

from __future__ import annotations

import json
from pathlib import Path


def write_manifest(state, out_dir: Path) -> None:
    """Write/update outputs/{session_id}_manifest.json for GUI consumption."""

    experts = []
    for i, e in enumerate(state.experts):
        expert_id = e.name.replace(".", "").replace(" ", "_").lower()
        experts.append({
            "id": expert_id,
            "name": e.name,
            "discipline": e.discipline,
            "bias": e.bias,
            "persona_prompt": e.persona_prompt,
            "color_index": i,
        })

    research_files: list[dict] = []
    for expert in experts:
        f = out_dir / f"{state.session_id}_research_{expert['id']}.md"
        if f.exists():
            research_files.append({
                "expert_id": expert["id"],
                "expert_name": expert["name"],
                "file": f.name,
            })
    agg = out_dir / f"{state.session_id}_research___aggregation__.md"
    if agg.exists():
        research_files.append({
            "expert_id": "__aggregation__",
            "expert_name": "Aggregator Summary",
            "file": agg.name,
        })

    rounds: list[dict] = []
    for r in range(state.max_audit_rounds + 2):
        t = out_dir / f"{state.session_id}_transcript_r{r}.md"
        s = out_dir / f"{state.session_id}_scorecard_r{r}.md"
        c = out_dir / f"{state.session_id}_consensus_r{r}.md"
        if t.exists() or s.exists():
            rounds.append({
                "round": r,
                "transcript": t.name if t.exists() else None,
                "scorecard": s.name if s.exists() else None,
                "consensus": c.name if c.exists() else None,
            })

    # Legacy fallback: single-file transcript/scorecard without round suffix
    if not rounds:
        t = out_dir / f"{state.session_id}_transcript.md"
        s = out_dir / f"{state.session_id}_scorecard.md"
        if t.exists() or s.exists():
            rounds.append({
                "round": 0,
                "transcript": t.name if t.exists() else None,
                "scorecard": s.name if s.exists() else None,
                "consensus": None,
            })

    panel = out_dir / f"{state.session_id}_panel.json"
    dossier = out_dir / f"{state.session_id}_dossier.md"

    phases_complete: list[str] = []
    if panel.exists():
        phases_complete.append("A")
    if research_files:
        phases_complete.append("B")
    if rounds:
        phases_complete.append("C")
    if any(r.get("consensus") for r in rounds):
        phases_complete.append("D")
    if dossier.exists():
        phases_complete.append("E")

    manifest = {
        "session_id": state.session_id,
        "query": state.query,
        "status": state.status,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "expectation_type": state.expectation_type,
        "expectation_detail": state.expectation_detail,
        "expectation_criteria": state.expectation_criteria,
        "experts": experts,
        "audit_rounds": len(rounds),
        "files": {
            "panel": panel.name if panel.exists() else None,
            "research": research_files,
            "rounds": rounds,
            "dossier": dossier.name if dossier.exists() else None,
        },
        "phases_complete": phases_complete,
    }

    out_dir.mkdir(exist_ok=True)
    manifest_path = out_dir / f"{state.session_id}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
