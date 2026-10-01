from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models import (
    CommunicationDraft,
    DetectionGap,
    Incident,
    IncidentEvent,
    IncidentState,
    TriageResult,
)

NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def _event(**overrides):
    payload = {
        "id": "evt-1",
        "timestamp": NOW,
        "actor": "human:vikrant",
        "event_type": "state_transition",
        "from_state": IncidentState.DETECTED,
        "to_state": IncidentState.TRIAGING,
        "reasoning": "ingestion complete",
    }
    payload.update(overrides)
    return IncidentEvent(**payload)


def _incident(**overrides):
    payload = {
        "id": "inc-1",
        "title": "Core banking latency",
        "current_state": IncidentState.DETECTED,
        "created_at": NOW,
        "updated_at": NOW,
        "reporter": "datadog",
        "source": "datadog",
    }
    payload.update(overrides)
    return Incident(**payload)


def test_valid_incident_and_event():
    event = _event(actor="ai:grok:grok-4")
    incident = _incident(timeline=[event], priority="Low", impact_score=12)
    assert incident.current_state is IncidentState.DETECTED
    assert incident.timeline[0].actor == "ai:grok:grok-4"
    assert not hasattr(incident, "approvals")


@pytest.mark.parametrize(
    "actor",
    ["", "system", "admin", "ai:grok:", "human:", "grok", "ai:other:model"],
)
def test_event_rejects_bad_actor(actor):
    with pytest.raises(ValidationError):
        _event(actor=actor)


def test_approved_by_must_be_human():
    event = _event(approved_by="human:oncall")
    assert event.approved_by == "human:oncall"
    with pytest.raises(ValidationError):
        _event(approved_by="ai:grok:grok-4")


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_rejects_confidence_out_of_range(confidence):
    with pytest.raises(ValidationError):
        _event(confidence=confidence)
    with pytest.raises(ValidationError):
        TriageResult(
            priority="Low",
            impact_score=10,
            affected_users_estimate=0,
            affected_services=[],
            category="latency",
            routing_suggestion="platform",
            reasoning="n",
            confidence=confidence,
        )


@pytest.mark.parametrize("impact_score", [0, 101])
def test_rejects_bad_impact_score(impact_score):
    with pytest.raises(ValidationError):
        _incident(impact_score=impact_score)
    with pytest.raises(ValidationError):
        TriageResult(
            priority="Medium",
            impact_score=impact_score,
            affected_users_estimate=1,
            affected_services=["core"],
            category="latency",
            routing_suggestion="platform",
            reasoning="n",
            confidence=0.5,
        )


def test_rejects_bad_priority():
    with pytest.raises(ValidationError):
        _incident(priority="Urgent")
    with pytest.raises(ValidationError):
        TriageResult(
            priority="P1",
            impact_score=10,
            affected_users_estimate=1,
            affected_services=["core"],
            category="latency",
            routing_suggestion="platform",
            reasoning="n",
            confidence=0.5,
        )


def test_detection_gap_requires_evidence():
    gap = DetectionGap(
        gap_description="No latency SLO on core banking",
        evidence="Alert fired on generic host CPU, not service latency",
        suggested_monitoring_or_runbook_change="Add p99 latency monitor on CoreBanking-Prod",
        severity="High",
        discovered_during="triage",
    )
    assert gap.evidence
    with pytest.raises(ValidationError):
        DetectionGap(
            gap_description="missing monitor",
            evidence="",
            suggested_monitoring_or_runbook_change="add monitor",
            severity="Low",
            discovered_during="triage",
        )


def test_communication_draft_audience():
    draft = CommunicationDraft(
        audience="internal",
        channel="slack",
        subject="Investigating core banking latency",
        body="We are investigating elevated latency.",
        tone="direct",
        confidence=0.8,
    )
    assert draft.audience == "internal"
    with pytest.raises(ValidationError):
        CommunicationDraft(
            audience="twitter",
            channel="slack",
            subject="x",
            body="y",
            tone="casual",
            confidence=0.1,
        )
