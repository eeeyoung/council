"""
tests/test_state_extended.py

Additional CouncilState tests: audit result application, evidence scorecard
rendering, and AuditResult model validation.
"""

from __future__ import annotations

from council.state import (
    AuditResult,
    CouncilState,
    EvidenceEntry,
    ExpertDefinition,
    TranscriptEntry,
)


# ── AuditResult model ─────────────────────────────────────────────────────

def test_audit_result_approved():
    result = AuditResult(round=1, approved=True, verdict="APPROVED")
    assert result.approved is True
    assert result.verdict == "APPROVED"
    assert result.issues == []
    assert result.conflict_mandate is None


def test_audit_result_rejected_with_mandate():
    result = AuditResult(
        round=2,
        approved=False,
        verdict="REJECTED",
        issues=["Lazy consensus on point 3.", "Claim X is unsupported."],
        conflict_mandate="Address the unsupported claim about froth stability.",
    )
    assert result.approved is False
    assert len(result.issues) == 2
    assert "froth stability" in result.conflict_mandate


# ── apply_audit_result ────────────────────────────────────────────────────

def test_apply_audit_result_approved():
    state = CouncilState(query="Test", status="auditing")
    result = AuditResult(round=1, approved=True, verdict="APPROVED")
    state.apply_audit_result(result)

    assert len(state.audit_history) == 1
    assert state.audit_history[0].approved is True
    assert state.audit_round == 1
    assert state.status == "compiling"
    assert state.conflict_mandate is None


def test_apply_audit_result_rejected():
    state = CouncilState(query="Test", status="auditing")
    result = AuditResult(
        round=1,
        approved=False,
        verdict="REJECTED",
        issues=["Bad evidence."],
        conflict_mandate="Fix the evidence problem.",
    )
    state.apply_audit_result(result)

    assert len(state.audit_history) == 1
    assert state.audit_history[0].approved is False
    assert state.audit_round == 1
    assert state.status == "debating"
    assert state.conflict_mandate == "Fix the evidence problem."


def test_apply_audit_result_multiple_rounds():
    state = CouncilState(query="Test", status="auditing")
    state.apply_audit_result(AuditResult(round=1, approved=False, verdict="REJECTED"))
    state.status = "auditing"  # simulate re-entering audit
    state.apply_audit_result(AuditResult(round=2, approved=True, verdict="APPROVED"))

    assert len(state.audit_history) == 2
    assert state.audit_round == 2
    assert state.status == "compiling"
    assert state.conflict_mandate is None


# ── evidence_scorecard_text ───────────────────────────────────────────────

def test_scorecard_text_empty():
    state = CouncilState(query="Test")
    assert "not yet compiled" in state.evidence_scorecard_text


def test_scorecard_text_with_entries():
    state = CouncilState(query="Test")
    state.evidence_scorecard = [
        EvidenceEntry(claim="WIMPs are heavy.", agent_name="Dr. A", source_url="https://example.com/1"),
        EvidenceEntry(claim="Axions are light.", agent_name="Dr. B", source_url="https://example.com/2"),
    ]
    text = state.evidence_scorecard_text
    assert "Dr. A" in text
    assert "WIMPs are heavy" in text
    assert "https://example.com/1" in text
    assert "Dr. B" in text
    assert "https://example.com/2" in text


def test_scorecard_text_with_uncited():
    state = CouncilState(query="Test")
    state.evidence_scorecard = [
        EvidenceEntry(claim="No source for this.", agent_name="Dr. C", source_url="UNCITED"),
    ]
    text = state.evidence_scorecard_text
    assert "UNCITED" in text


# ── next_turn_number ──────────────────────────────────────────────────────

def test_next_turn_number_empty():
    state = CouncilState(query="Test")
    assert state.next_turn_number == 1


def test_next_turn_number_after_entries():
    state = CouncilState(query="Test")
    state.add_transcript_entry("Dr. A", "Physics", "Hello", phase="debate")
    state.add_transcript_entry("Dr. B", "Chemistry", "Hi", phase="debate")
    assert state.next_turn_number == 3


# ── transcript rendering with audit markers ───────────────────────────────

def test_transcript_text_audit_markers():
    state = CouncilState(query="Test")
    state.add_transcript_entry("Rapporteur", "Rapporteur", "Synthesis text.", phase="audit")
    state.add_transcript_entry("Discussant", "Discussant", "Rejected.", phase="audit")
    text = state.transcript_text
    assert "[RAPPORTEUR]" in text
    assert "[DISCUSSANT]" in text
    assert "**Rapporteur**" in text
    assert "**Discussant**" in text
    assert "Synthesis text." in text
    assert "Rejected." in text
