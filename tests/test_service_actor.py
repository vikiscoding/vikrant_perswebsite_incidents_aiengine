"""service:<name> actors (live site intake): may ingest, may never transition, approve or hand off."""

import pytest

from models import IncidentEvent, validate_actor, validate_intake_actor
from store import Store, StoreError
from ingest import ingest
from cmdb import Cmdb
from datetime import datetime, timezone

SERVICE = "service:vikrantsingh.fyi-heartbeat"
ALERT = {"monitor": "vikrantsingh.fyi heartbeat", "service": "vikrantsingh.fyi", "message": "ticker failed twice: http 503"}


def test_service_actor_is_intake_only():
    assert validate_intake_actor(SERVICE) == SERVICE
    with pytest.raises(ValueError):
        validate_actor(SERVICE)  # transitions, approvals and handoffs still refuse it


@pytest.mark.parametrize("bad", ["service:", "service", "system", "admin", ""])
def test_bad_intake_actors_still_refused(bad):
    with pytest.raises(ValueError):
        validate_intake_actor(bad)


def test_service_can_ingest_an_alert(tmp_path):
    store = Store(tmp_path)
    incident = ingest(store, "alert", ALERT, SERVICE, Cmdb.load())
    created = incident.timeline[0]
    assert created.event_type == "incident_created" and created.actor == SERVICE
    assert incident.current_state.value == "DETECTED"


def test_service_cannot_transition(tmp_path):
    store = Store(tmp_path)
    incident = ingest(store, "alert", ALERT, SERVICE, Cmdb.load())
    with pytest.raises((ValueError, StoreError)):
        store.transition(incident.id, "TRIAGING", SERVICE, "trying to move it")


def test_service_cannot_write_other_event_types():
    with pytest.raises(ValueError):
        IncidentEvent(id="evt-x", timestamp=datetime.now(timezone.utc), actor=SERVICE, event_type="note", reasoning="no")


def test_service_cannot_approve():
    with pytest.raises(ValueError):
        IncidentEvent(
            id="evt-y", timestamp=datetime.now(timezone.utc), actor="human:vikiscoding", event_type="triage_approved",
            reasoning="x", approved_by=SERVICE,
        )
