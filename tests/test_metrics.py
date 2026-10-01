import json

from models import IncidentState
from store import Store

HUMAN = "human:vikrant"
AI = "ai:grok:grok-4"


def test_lifecycle_emits_dwell_and_triage_latency(tmp_path):
    store = Store(tmp_path)
    incident = store.create_incident(
        title="website 5xx",
        reporter="alert:web",
        source="alert",
        actor=HUMAN,
    )
    store.transition(incident.id, IncidentState.TRIAGING, AI, "start triage")

    records = {row["metric"]: row for row in store.metric_records(incident.id)}
    assert "create_latency_ms" in records
    assert "state_dwell_ms" in records
    assert records["state_dwell_ms"]["labels"]["state"] == "DETECTED"
    assert records["time_to_triage_ms"]["value"] >= 0
    assert store.get_incident(incident.id).current_state is IncidentState.TRIAGING

    lines = (tmp_path / "runtime" / "metrics.jsonl").read_text(encoding="utf-8").strip().splitlines()
    parsed = [json.loads(line) for line in lines]
    names = {row["metric"] for row in parsed}
    assert {"create_latency_ms", "state_dwell_ms", "time_to_triage_ms"} <= names
    assert all(row["incident_id"] == incident.id for row in parsed)


def test_metric_does_not_change_state(tmp_path):
    store = Store(tmp_path)
    incident = store.create_incident(
        title="note",
        reporter="human:vikrant",
        source="manual",
        actor=HUMAN,
    )
    updated = store.emit_metric(incident.id, "duplicate_detected", 0, HUMAN, labels={"field": "title"})
    assert updated.current_state is IncidentState.DETECTED
    assert updated.timeline[-1].event_type == "metric"
    assert updated.timeline[-1].to_state is None


def test_secret_labels_are_dropped(tmp_path):
    store = Store(tmp_path)
    incident = store.create_incident(
        title="auth",
        reporter="human:vikrant",
        source="manual",
        actor=HUMAN,
    )
    store.emit_metric(
        incident.id,
        "ai_call_error",
        1,
        HUMAN,
        labels={"api_key": "sk-secret", "model": "grok-4"},
    )
    row = store.metric_records(incident.id)[-1]
    assert "api_key" not in row["labels"]
    assert row["labels"]["model"] == "grok-4"
    jsonl = (tmp_path / "runtime" / "metrics.jsonl").read_text(encoding="utf-8")
    assert "sk-secret" not in jsonl


def test_failed_transition_emits_no_dwell(tmp_path):
    store = Store(tmp_path)
    incident = store.create_incident(
        title="x",
        reporter="human:vikrant",
        source="manual",
        actor=HUMAN,
    )
    before = {row["metric"] for row in store.metric_records(incident.id)}
    try:
        store.transition(incident.id, IncidentState.CLOSED, HUMAN, "skip")
    except Exception:
        pass
    after = {row["metric"] for row in store.metric_records(incident.id)}
    assert after == before
    assert "state_dwell_ms" not in after
