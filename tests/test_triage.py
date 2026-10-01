import json

import httpx
import pytest

from grok import GrokClient
from ingest import ingest_alert
from models import IncidentState
from store import Store, StoreError
from triage import approve_triage, override_triage, reject_triage, run_triage
from cmdb import Cmdb

HUMAN = "human:vikrant"
AI = "ai:grok:grok-4.5"


def _proposal(**overrides):
    payload = {
        "priority": "Low",
        "impact_score": 18,
        "affected_users_estimate": 200,
        "affected_services": ["website-web"],
        "category": "availability",
        "routing_suggestion": "Application",
        "duplicate_of": None,
        "reasoning": "Public website 5xx on a critical CI; user impact limited so far.",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return payload


def _grok(store: Store, body: dict) -> GrokClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(body)}}]},
        )

    return GrokClient(
        store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        api_key="test-key",
        model="grok-4.5",
    )


def _ingest(store: Store):
    return ingest_alert(
        store,
        {
            "monitor": "website-web-5xx",
            "service": "website-web",
            "message": "5xx rate above 5%",
            "severity": "critical",
        },
        HUMAN,
        Cmdb.load(),
    )


def test_low_priority_auto_applies_and_reloads(tmp_path):
    store = Store(tmp_path)
    created = _ingest(store)
    outcome = run_triage(store, _grok(store, _proposal()), created.id)
    assert outcome.applied is True
    assert outcome.requires_approval is False
    assert outcome.incident.priority == "Low"
    assert outcome.incident.impact_score == 18
    assert outcome.incident.ai_triage is not None
    assert outcome.incident.current_state is IncidentState.TRIAGING
    assert outcome.trace_path
    assert (tmp_path / "incidents" / created.id / outcome.trace_path).is_file()

    reloaded = Store(tmp_path).get_incident(created.id)
    assert reloaded.priority == "Low"
    assert reloaded.ai_triage.routing_suggestion == "Application"
    names = {row["metric"] for row in store.metric_records(created.id)}
    assert "ai_confidence" in names
    assert "duplicate_detected" in names
    assert store.transition(created.id, IncidentState.ACKNOWLEDGED, AI, "ack after auto triage").current_state is IncidentState.ACKNOWLEDGED


def test_critical_proposal_is_gated_until_human_approves(tmp_path):
    store = Store(tmp_path)
    created = _ingest(store)
    outcome = run_triage(store, _grok(store, _proposal(priority="Critical", impact_score=92, confidence=0.95)), created.id)
    assert outcome.applied is False
    assert outcome.requires_approval is True
    assert outcome.incident.priority is None
    assert outcome.incident.ai_triage.priority == "Critical"

    with pytest.raises(StoreError, match="human"):
        approve_triage(store, created.id, AI)

    approved = approve_triage(store, created.id, HUMAN)
    assert approved.priority == "Critical"
    assert approved.impact_score == 92
    again = Store(tmp_path).get_incident(created.id)
    assert again.priority == "Critical"


def test_low_confidence_medium_is_gated(tmp_path):
    store = Store(tmp_path)
    created = _ingest(store)
    outcome = run_triage(store, _grok(store, _proposal(priority="Medium", confidence=0.4)), created.id)
    assert outcome.applied is False
    assert outcome.requires_approval is True
    assert outcome.incident.priority is None


def test_override_is_a_new_event(tmp_path):
    store = Store(tmp_path)
    created = _ingest(store)
    run_triage(store, _grok(store, _proposal()), created.id)
    updated = override_triage(store, created.id, HUMAN, "priority", "High", "blast radius includes checkout")
    assert updated.priority == "High"
    overrides = [event for event in updated.timeline if event.event_type == "human_override"]
    assert len(overrides) == 1
    assert overrides[0].payload["previous"] == "Low"
    assert Store(tmp_path).get_incident(created.id).priority == "High"


def test_failed_model_does_not_invent_priority(tmp_path):
    store = Store(tmp_path)
    created = _ingest(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    grok = GrokClient(
        store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        api_key="test-key",
        model="grok-4.5",
    )
    outcome = run_triage(store, grok, created.id)
    assert outcome.proposal is None
    assert outcome.incident.priority is None
    assert outcome.incident.ai_triage is None
    assert any(event.event_type == "triage_failed" for event in outcome.incident.timeline)
    assert outcome.incident.current_state is IncidentState.TRIAGING


def test_reject_clears_applied_priority(tmp_path):
    store = Store(tmp_path)
    created = _ingest(store)
    run_triage(store, _grok(store, _proposal()), created.id)
    rejected = reject_triage(store, created.id, HUMAN, "wrong service")
    assert rejected.priority is None
    assert rejected.ai_triage is not None


def test_intake_severity_is_not_copied(tmp_path):
    store = Store(tmp_path)
    created = _ingest(store)
    assert created.priority is None
    outcome = run_triage(store, _grok(store, _proposal(priority="Low")), created.id)
    assert outcome.incident.priority == "Low"
