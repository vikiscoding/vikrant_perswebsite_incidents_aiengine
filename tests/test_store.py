import json
import sqlite3

import pytest

from models import IncidentEvent, IncidentState
from store import Store, StoreError, materialize_from_events


AI = "ai:grok:grok-4"
HUMAN = "human:vikrant"


def _domain_types(events):
    return [event.event_type for event in events if event.event_type != "metric"]


def _create(store: Store, **overrides):
    payload = {
        "title": "Core banking latency",
        "reporter": "pager",
        "source": "datadog",
        "actor": HUMAN,
        "raw_payload": {"alert": "p99_latency", "service": "CoreBanking-Prod"},
    }
    payload.update(overrides)
    return store.create_incident(**payload)


def test_create_transition_reload_reconstructs_timeline(tmp_path):
    store = Store(tmp_path)
    created = _create(store, incident_id="inc-reload")
    store.transition(created.id, IncidentState.TRIAGING, AI, "start triage")

    reopened = Store(tmp_path)
    loaded = reopened.get_incident("inc-reload")
    events = reopened.get_events("inc-reload")

    assert loaded.current_state is IncidentState.TRIAGING
    assert _domain_types(loaded.timeline) == ["incident_created", "state_transition"]
    assert loaded.timeline == events
    assert loaded.id == created.id
    assert loaded.title == created.title
    rebuilt = materialize_from_events(events)
    assert rebuilt.current_state is IncidentState.TRIAGING
    assert rebuilt.timeline[0].to_state is IncidentState.DETECTED
    transition = next(event for event in rebuilt.timeline if event.event_type == "state_transition")
    assert transition.from_state is IncidentState.DETECTED


def test_create_writes_artifact_tree_and_raw_input(tmp_path):
    store = Store(tmp_path)
    incident = _create(store, incident_id="inc-files")
    folder = tmp_path / "incidents" / "inc-files"
    raw = folder / "raw_inputs" / "intake.json"
    assert (folder / "incident.json").is_file()
    assert (folder / "ai_traces").is_dir()
    assert json.loads(raw.read_text(encoding="utf-8"))["service"] == "CoreBanking-Prod"
    assert incident.timeline[0].artifacts == ["raw_inputs/intake.json"]

    with pytest.raises(StoreError, match="immutable"):
        store.write_raw_input("inc-files", "intake.json", {"alert": "duplicate"})
    assert json.loads(raw.read_text(encoding="utf-8"))["service"] == "CoreBanking-Prod"


def test_illegal_transition_writes_no_event(tmp_path):
    store = Store(tmp_path)
    incident = _create(store)
    with pytest.raises(StoreError, match="illegal"):
        store.transition(incident.id, IncidentState.CLOSED, HUMAN, "skip ahead")
    events = store.get_events(incident.id)
    assert _domain_types(events) == ["incident_created"]
    assert store.get_incident(incident.id).current_state is IncidentState.DETECTED


def test_ai_cannot_resolve(tmp_path):
    store = Store(tmp_path)
    incident = _create(store)
    store.transition(incident.id, IncidentState.TRIAGING, AI, "triage")
    # No priority yet (triage is Slice 6) — ack is fail-closed and needs a human.
    store.transition(incident.id, IncidentState.ACKNOWLEDGED, HUMAN, "ack")
    store.transition(incident.id, IncidentState.ACTIVE, AI, "work starts")
    with pytest.raises(StoreError, match="human"):
        store.transition(incident.id, IncidentState.RESOLVED, AI, "AI closes")
    assert store.get_incident(incident.id).current_state is IncidentState.ACTIVE


def test_events_are_append_only(tmp_path):
    store = Store(tmp_path)
    incident = _create(store)
    event_id = incident.timeline[0].id
    conn = sqlite3.connect(tmp_path / "incidents.db")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE incident_events SET actor = 'human:other' WHERE id = ?", (event_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM incident_events WHERE id = ?", (event_id,))
    conn.close()
    assert store.get_events(incident.id)[0].actor == HUMAN


def test_corrupt_incident_json_still_loads_from_events(tmp_path):
    store = Store(tmp_path)
    incident = _create(store, incident_id="inc-ssot")
    store.transition(incident.id, IncidentState.TRIAGING, AI, "triage")
    json_path = tmp_path / "incidents" / "inc-ssot" / "incident.json"
    json_path.write_text("not-json", encoding="utf-8")
    loaded = Store(tmp_path).get_incident("inc-ssot")
    assert loaded.current_state is IncidentState.TRIAGING
    assert _domain_types(loaded.timeline) == ["incident_created", "state_transition"]


def test_create_rejects_anonymous_actor(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(ValueError, match="actor"):
        _create(store, actor="system")


def test_duplicate_incident_id_rejected(tmp_path):
    store = Store(tmp_path)
    _create(store, incident_id="inc-dup")
    with pytest.raises(StoreError, match="already exists"):
        _create(store, incident_id="inc-dup")


def test_append_event_cannot_bypass_guard(tmp_path):
    store = Store(tmp_path)
    incident = _create(store)
    sneak = IncidentEvent(
        id="evt-sneak",
        timestamp=incident.created_at,
        actor=HUMAN,
        event_type="state_transition",
        from_state=IncidentState.DETECTED,
        to_state=IncidentState.CLOSED,
        reasoning="bypass",
    )
    with pytest.raises(StoreError, match="illegal"):
        store.append_event(incident.id, sneak)
    assert _domain_types(store.get_events(incident.id)) == ["incident_created"]
