import json
from pathlib import Path

import httpx
import pytest

from cli import main
from grok import GrokClient
from store import Store

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "alert_website_5xx.json"
HUMAN = "human:vikrant"
AI = "ai:grok:grok-4.5"


def _run(root: Path, *argv: str) -> tuple[int, str]:
    import io
    import sys

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        code = main(["--root", str(root), *argv])
    finally:
        sys.stdout = old
    return code, buf.getvalue()


def test_lifecycle_detected_to_closed_with_human_gates(tmp_path):
    code, out = _run(tmp_path, "ingest", "--source", "alert", "--file", str(FIXTURE), "--actor", HUMAN)
    assert code == 0
    incident_id = out.splitlines()[0].strip()
    assert incident_id.startswith("inc-")

    assert _run(tmp_path, "transition", "--id", incident_id, "--to", "CLOSED", "--actor", HUMAN, "--reason", "skip", "--confirm", "CLOSED")[0] == 1

    assert _run(tmp_path, "transition", "--id", incident_id, "--to", "TRIAGING", "--actor", AI, "--reason", "start")[0] == 0
    assert _run(tmp_path, "override", "--id", incident_id, "--actor", HUMAN, "--field", "priority", "--value", "Medium", "--reason", "contained")[0] == 0
    assert _run(tmp_path, "transition", "--id", incident_id, "--to", "ACKNOWLEDGED", "--actor", AI, "--reason", "acked")[0] == 0
    assert _run(tmp_path, "transition", "--id", incident_id, "--to", "ACTIVE", "--actor", AI, "--reason", "working")[0] == 0
    assert _run(tmp_path, "note", "--id", incident_id, "--actor", HUMAN, "--text", "rolled back deploy")[0] == 0
    assert _run(tmp_path, "transition", "--id", incident_id, "--to", "RESOLVED", "--actor", HUMAN, "--reason", "verified", "--confirm", "RESOLVED")[0] == 0
    code, out = _run(
        tmp_path, "transition", "--id", incident_id, "--to", "CLOSED", "--actor", HUMAN, "--reason", "signed off", "--confirm", "CLOSED"
    )
    assert code == 0
    assert "CLOSED" in out

    code, shown = _run(tmp_path, "show", incident_id)
    assert code == 0
    assert "CLOSED" in shown
    assert "rolled back deploy" in shown or "note" in shown

    export_path = tmp_path / "export.json"
    assert _run(tmp_path, "export", "--id", incident_id, "--out", str(export_path))[0] == 0
    assert export_path.is_file()
    folder = tmp_path / "incidents" / incident_id
    assert (folder / "incident.json").is_file()
    assert Store(tmp_path).get_incident(incident_id).current_state.value == "CLOSED"


def test_approve_rejects_ai_actor(tmp_path):
    code, out = _run(tmp_path, "ingest", "--source", "alert", "--file", str(FIXTURE), "--actor", HUMAN)
    incident_id = out.splitlines()[0].strip()
    code, err = _run(tmp_path, "approve", "--id", incident_id, "--actor", AI)
    assert code == 1


def _scripted_grok(store: Store) -> GrokClient:
    replies = [
        {
            "priority": "Low",
            "impact_score": 20,
            "affected_users_estimate": 100,
            "affected_services": ["website-web"],
            "category": "availability",
            "routing_suggestion": "Application",
            "duplicate_of": None,
            "reasoning": "Contained 5xx on website-web.",
            "confidence": 0.91,
        },
        {
            "audience": "customers",
            "channel": "status_page",
            "subject": "We are investigating website errors",
            "body": "We are aware of errors on the website and are investigating.",
            "tone": "calm",
            "expected_resolution_window": "investigating",
            "confidence": 0.88,
        },
        {
            "audience": "internal",
            "channel": "slack",
            "subject": "Status: website-web 5xx",
            "body": "Investigating 5xx on website-web. No root cause yet.",
            "tone": "direct",
            "expected_resolution_window": "investigating",
            "confidence": 0.86,
        },
        {
            "gaps": [
                {
                    "gap_description": "No SLO burn alert on website-web",
                    "evidence": "Alert is a raw 5xx rate, not SLO burn on CI-APP-001.",
                    "suggested_monitoring_or_runbook_change": "Add SLO burn-rate monitor on website-web.",
                    "severity": "High",
                    "discovered_during": "triage",
                    "status": "proposed",
                }
            ],
            "confidence": 0.84,
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = replies.pop(0)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    return GrokClient(
        store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        api_key="test-key",
        model="grok-4.5",
    )


def test_propose_then_show_prints_drafts_and_gaps(tmp_path, monkeypatch):
    monkeypatch.setattr("cli._grok", lambda store: _scripted_grok(store))
    code, out = _run(tmp_path, "ingest", "--source", "alert", "--file", str(FIXTURE), "--actor", HUMAN)
    incident_id = out.splitlines()[0].strip()
    code, proposed = _run(tmp_path, "propose", "--id", incident_id)
    assert code == 0
    assert "sent=False" in proposed or "sent=false" in proposed.lower()

    incident = Store(tmp_path).get_incident(incident_id)
    assert len(incident.communications) >= 2
    assert len(incident.detection_gaps) >= 1
    drafted = [event for event in incident.timeline if event.event_type == "communication_drafted"]
    assert drafted
    assert all(event.payload.get("sent") is False for event in drafted)

    code, shown = _run(tmp_path, "show", incident_id)
    assert code == 0
    assert "We are aware of errors on the website" in shown
    assert "No SLO burn alert on website-web" in shown
    assert "High" in shown
    assert "sent=false" in shown
