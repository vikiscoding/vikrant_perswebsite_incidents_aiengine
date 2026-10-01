import json

import httpx
import pytest

from comms import draft_ack_and_status, draft_communication
from grok import GrokClient
from models import IncidentState
from store import Store

HUMAN = "human:vikrant"


def _draft(audience: str, subject: str, body: str) -> dict:
    return {
        "audience": audience,
        "channel": "status_page" if audience == "customers" else "slack",
        "subject": subject,
        "body": body,
        "tone": "calm",
        "expected_resolution_window": "investigating",
        "confidence": 0.88,
    }


def _grok(store: Store) -> GrokClient:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        user = payload["messages"][1]["content"]
        if '"kind": "ack"' in user or "kind=ack" in user:
            body = _draft("customers", "We are investigating website errors", "We are aware of errors on the website and are investigating.")
        else:
            body = _draft("internal", "Status: website-web 5xx", "Investigating 5xx on website-web. No root cause yet.")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    return GrokClient(
        store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        api_key="test-key",
        model="grok-4.5",
    )


def _incident(store: Store):
    return store.create_incident(
        title="website-web 5xx",
        reporter="alert:web",
        source="alert",
        actor=HUMAN,
        affected_services=["website-web"],
        affected_ci_ids=["CI-APP-001"],
    )


def test_ack_and_status_are_drafts_not_sent(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)
    ack, status = draft_ack_and_status(store, _grok(store), created.id)
    assert ack.error is None and status.error is None
    assert ack.draft.audience == "customers"
    assert status.draft.audience == "internal"
    assert len(ack.incident.communications) == 1
    loaded = Store(tmp_path).get_incident(created.id)
    assert len(loaded.communications) == 2
    assert loaded.current_state is IncidentState.DETECTED
    drafted = [event for event in loaded.timeline if event.event_type == "communication_drafted"]
    assert len(drafted) == 2
    assert all(event.payload.get("sent") is False for event in drafted)
    names = {row["metric"] for row in store.metric_records(created.id)}
    assert "time_to_first_ack_draft_ms" in names
    assert ack.trace_path
    assert (tmp_path / "incidents" / created.id / ack.trace_path).is_file()


def test_failed_draft_does_not_invent_text(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    grok = GrokClient(
        store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        api_key="test-key",
        model="grok-4.5",
    )
    outcome = draft_communication(store, grok, created.id, "ack", "customers")
    assert outcome.draft is None
    assert created.id == outcome.incident.id
    assert outcome.incident.communications == []
    assert any(event.event_type == "communication_failed" for event in outcome.incident.timeline)


def test_second_ack_does_not_repeat_first_ack_metric(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)
    grok = _grok(store)
    draft_communication(store, grok, created.id, "ack", "customers")
    draft_communication(store, grok, created.id, "ack", "internal")
    ack_metrics = [row for row in store.metric_records(created.id) if row["metric"] == "time_to_first_ack_draft_ms"]
    assert len(ack_metrics) == 1
