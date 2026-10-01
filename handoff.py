"""Assignment and support-group changes are events. Typed confirm, not a game."""

import uuid
from typing import Optional

from company import get_company
from models import Incident, IncidentEvent, is_human_actor, validate_actor
from store import Store, StoreError, _utcnow


def require_typed_confirm(expected: str, got: Optional[str]) -> None:
    if got != expected:
        raise StoreError(f"type {expected} to confirm (got {got!r})")


def assert_can_act(incident: Incident, actor: str, *, steal: bool = False) -> None:
    holder = incident.assigned_to
    if holder and holder != actor and not steal:
        raise StoreError(f"held by {holder}; release first or pass --steal with a reason")


def _event(actor: str, event_type: str, reasoning: str, **kwargs) -> IncidentEvent:
    return IncidentEvent(
        id=f"evt-{uuid.uuid4().hex[:12]}",
        timestamp=_utcnow(),
        actor=actor,
        event_type=event_type,
        reasoning=reasoning,
        **kwargs,
    )


def assign(store: Store, incident_id: str, actor: str, holder: str, reason: str, *, steal: bool = False) -> Incident:
    validate_actor(actor)
    if not is_human_actor(actor):
        raise StoreError("assign requires a human actor")
    validate_actor(holder)
    if not is_human_actor(holder):
        raise StoreError("holder must be human:<id>")
    incident = store.get_incident(incident_id)
    assert_can_act(incident, actor, steal=steal)
    if steal and not reason:
        raise StoreError("steal requires a reason")
    store.append_event(
        incident_id,
        _event(
            actor,
            "assignment_changed",
            reason,
            payload={
                "from": incident.assigned_to,
                "to": holder,
                "steal": steal,
                "reason": reason,
            },
        ),
    )
    return store.get_incident(incident_id)


def release(store: Store, incident_id: str, actor: str, reason: str) -> Incident:
    validate_actor(actor)
    if not is_human_actor(actor):
        raise StoreError("release requires a human actor")
    incident = store.get_incident(incident_id)
    if not incident.assigned_to:
        raise StoreError("incident is not held")
    if incident.assigned_to != actor:
        raise StoreError(f"only {incident.assigned_to} can release (or steal then release)")
    store.append_event(
        incident_id,
        _event(
            actor,
            "released",
            reason,
            payload={"from": incident.assigned_to, "to": None, "reason": reason},
        ),
    )
    return store.get_incident(incident_id)


def route(store: Store, incident_id: str, actor: str, group: str, reason: str) -> Incident:
    validate_actor(actor)
    if not is_human_actor(actor):
        raise StoreError("route requires a human actor")
    allowed = get_company().owning_teams()
    if group not in allowed:
        raise StoreError(f"support group must be one of {sorted(allowed)}")
    incident = store.get_incident(incident_id)
    if incident.support_group == group:
        raise StoreError(f"support group already {group}")
    store.append_event(
        incident_id,
        _event(
            actor,
            "support_group_changed",
            reason,
            payload={"from": incident.support_group, "to": group, "reason": reason},
        ),
    )
    return store.get_incident(incident_id)
