import json

import httpx
import pytest

from gaps import analyze_gaps, set_gap_status
from grok import GrokClient
from store import Store, StoreError

HUMAN = "human:vikrant"
AI = "ai:grok:grok-4.5"


def _batch(*gaps):
    return {"gaps": list(gaps), "confidence": 0.86}


def _gap(description: str, severity: str = "High") -> dict:
    return {
        "gap_description": description,
        "evidence": "Alert is host CPU, not p99 latency on website-web (CI-APP-001).",
        "suggested_monitoring_or_runbook_change": "Add p99 5xx monitor on website-web.",
        "severity": severity,
        "discovered_during": "triage",
        "status": "proposed",
    }


def _grok(store: Store, body: dict) -> GrokClient:
    def handler(request: httpx.Request) -> httpx.Response:
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
        affected_ci_ids=["CI-APP-001"],
    )


def test_propose_gaps_and_reload(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)
    outcome = analyze_gaps(
        store,
        _grok(store, _batch(_gap("No SLO on website-web"), _gap("CDN origin errors unpaged", "Medium"))),
        created.id,
    )
    assert outcome.error is None
    assert len(outcome.added) == 2
    assert all(gap.evidence for gap in outcome.incident.detection_gaps)
    loaded = Store(tmp_path).get_incident(created.id)
    assert len(loaded.detection_gaps) == 2
    counts = [row for row in store.metric_records(created.id) if row["metric"] == "detection_gap_count"]
    assert any(row["labels"]["severity"] == "High" and row["value"] == 1 for row in counts)
    assert outcome.trace_path
    assert (tmp_path / "incidents" / created.id / outcome.trace_path).is_file()


def test_second_pass_does_not_delete_confirmed(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)
    analyze_gaps(store, _grok(store, _batch(_gap("No SLO on website-web"))), created.id)
    set_gap_status(store, created.id, HUMAN, "No SLO on website-web", "confirmed")
    analyze_gaps(
        store,
        _grok(store, _batch(_gap("No SLO on website-web"), _gap("Missing checkout synthetic"))),
        created.id,
    )
    loaded = store.get_incident(created.id)
    by_desc = {gap.gap_description: gap for gap in loaded.detection_gaps}
    assert by_desc["No SLO on website-web"].status == "confirmed"
    assert "Missing checkout synthetic" in by_desc


def test_human_required_to_change_status(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)
    analyze_gaps(store, _grok(store, _batch(_gap("No SLO on website-web"))), created.id)
    with pytest.raises(StoreError, match="human"):
        set_gap_status(store, created.id, AI, "No SLO on website-web", "rejected")


def test_empty_evidence_rejected_by_schema(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)
    outcome = analyze_gaps(
        store,
        _grok(
            store,
            _batch(
                {
                    "gap_description": "vague",
                    "evidence": "",
                    "suggested_monitoring_or_runbook_change": "monitor more",
                    "severity": "Low",
                    "discovered_during": "triage",
                }
            ),
        ),
        created.id,
    )
    assert outcome.added == []
    assert outcome.incident.detection_gaps == []
    assert outcome.error


def test_model_failure_adds_no_gaps(tmp_path):
    store = Store(tmp_path)
    created = _incident(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    grok = GrokClient(store, client=httpx.Client(transport=httpx.MockTransport(handler)), api_key="test-key", model="grok-4.5")
    outcome = analyze_gaps(store, grok, created.id)
    assert outcome.added == []
    assert any(event.event_type == "detection_gaps_failed" for event in outcome.incident.timeline)
