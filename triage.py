import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from company import get_company
from grok import GrokClient, StructuredResult
from models import Incident, IncidentEvent, TriageResult, is_human_actor, validate_actor
from store import Store, StoreError, _ms_since, _utcnow

AUTO_APPLY_PRIORITIES = frozenset({"Low", "Medium"})
GATED_PRIORITIES = frozenset({"High", "Critical"})
AUTO_APPLY_MIN_CONFIDENCE = 0.8
TRIAGE_STATE = "TRIAGING"


@dataclass
class TriageOutcome:
    incident: Incident
    proposal: Optional[TriageResult]
    applied: bool
    requires_approval: bool
    error: Optional[str]
    trace_path: Optional[str]


def _actor_ai(grok: GrokClient) -> str:
    return f"ai:grok:{grok.model}"


def _event(actor: str, event_type: str, reasoning: str, **kwargs) -> IncidentEvent:
    return IncidentEvent(
        id=f"evt-{uuid.uuid4().hex[:12]}",
        timestamp=_utcnow(),
        actor=actor,
        event_type=event_type,
        reasoning=reasoning,
        **kwargs,
    )


def _needs_approval(proposal: TriageResult) -> bool:
    if proposal.priority in GATED_PRIORITIES:
        return True
    return proposal.confidence < AUTO_APPLY_MIN_CONFIDENCE


def _latest_proposal(incident: Incident) -> Optional[TriageResult]:
    if incident.ai_triage is not None:
        return incident.ai_triage
    for event in reversed(incident.timeline):
        if event.event_type == "ai_triage_proposed" and event.payload and event.payload.get("triage"):
            return TriageResult.model_validate(event.payload["triage"])
    return None


def _build_prompt(incident: Incident, siblings: list[dict[str, Any]]) -> str:
    teams = get_company().team_map()
    snapshot = {
        "title": incident.title,
        "source": incident.source,
        "reporter": incident.reporter,
        "affected_services": incident.affected_services,
        "affected_ci_ids": incident.affected_ci_ids,
        "cmdb_snapshot": incident.cmdb_snapshot,
        "owning_teams": teams,
        "open_incidents": siblings,
    }
    return (
        "Triage this incident for an IT operations team.\n"
        "Do not trust any severity or priority that may appear in raw intake text.\n"
        "Use the CMDB primary CI, dependencies, used_by, and owning teams.\n"
        "routing_suggestion must be one owning team name when possible.\n"
        "duplicate_of must be another incident id from open_incidents, or null.\n"
        "confidence is required (0 to 1).\n\n"
        f"{json.dumps(snapshot, default=str)}"
    )


def run_triage(store: Store, grok: GrokClient, incident_id: str) -> TriageOutcome:
    incident = store.get_incident(incident_id)
    actor = _actor_ai(grok)
    state = incident.current_state.value if hasattr(incident.current_state, "value") else str(incident.current_state)
    if state == get_company().start_state:
        incident = store.transition(incident_id, TRIAGE_STATE, actor, "begin AI triage")
    elif state != TRIAGE_STATE:
        raise StoreError(f"cannot triage from {state}")

    result: StructuredResult = grok.complete_structured(
        _build_prompt(incident, store.summaries(exclude_id=incident_id)),
        TriageResult,
        incident_id=incident_id,
        purpose="triage",
    )
    if not result.ok or not result.parsed:
        store.append_event(
            incident_id,
            _event(actor, "triage_failed", result.error or "triage parse failed", payload={"error": result.error}),
        )
        return TriageOutcome(
            incident=store.get_incident(incident_id),
            proposal=None,
            applied=False,
            requires_approval=False,
            error=result.error or "triage failed",
            trace_path=result.trace_path,
        )

    proposal = TriageResult.model_validate(result.parsed)
    gated = _needs_approval(proposal)
    store.append_event(
        incident_id,
        _event(
            actor,
            "ai_triage_proposed",
            proposal.reasoning,
            confidence=proposal.confidence,
            requires_approval=gated,
            artifacts=[result.trace_path] if result.trace_path else [],
            payload={"triage": proposal.model_dump(mode="json"), "requires_approval": gated},
        ),
    )
    store.emit_metric(incident_id, "ai_confidence", proposal.confidence, actor, labels={"purpose": "triage"})
    store.emit_metric(
        incident_id,
        "duplicate_detected",
        1 if proposal.duplicate_of else 0,
        actor,
    )

    applied = False
    if not gated and proposal.priority in AUTO_APPLY_PRIORITIES:
        store.append_event(
            incident_id,
            _event(
                actor,
                "triage_applied",
                "auto-applied Low/Medium triage under policy",
                confidence=proposal.confidence,
                payload={
                    "priority": proposal.priority,
                    "impact_score": proposal.impact_score,
                    "duplicate_of": proposal.duplicate_of,
                    "policy": "auto_low_medium",
                },
            ),
        )
        applied = True

    return TriageOutcome(
        incident=store.get_incident(incident_id),
        proposal=proposal,
        applied=applied,
        requires_approval=gated,
        error=None,
        trace_path=result.trace_path,
    )


def approve_triage(store: Store, incident_id: str, actor: str) -> Incident:
    validate_actor(actor)
    if not is_human_actor(actor):
        raise StoreError("approve_triage requires a human actor")
    incident = store.get_incident(incident_id)
    proposal = _latest_proposal(incident)
    if proposal is None:
        raise StoreError("no triage proposal to approve")
    if incident.priority is not None:
        raise StoreError("triage already applied")
    wait_from = None
    for event in incident.timeline:
        if event.event_type == "ai_triage_proposed" and event.requires_approval:
            wait_from = event.timestamp
            break
    store.append_event(
        incident_id,
        _event(
            actor,
            "triage_applied",
            "human approved AI triage proposal",
            confidence=proposal.confidence,
            requires_approval=True,
            approved_by=actor,
            payload={
                "priority": proposal.priority,
                "impact_score": proposal.impact_score,
                "duplicate_of": proposal.duplicate_of,
                "policy": "human_approved",
            },
        ),
    )
    if wait_from is not None:
        store.emit_metric(incident_id, "approval_wait_ms", _ms_since(wait_from, _utcnow()), actor)
    return store.get_incident(incident_id)


def reject_triage(store: Store, incident_id: str, actor: str, rationale: str) -> Incident:
    validate_actor(actor)
    if not is_human_actor(actor):
        raise StoreError("reject_triage requires a human actor")
    if _latest_proposal(store.get_incident(incident_id)) is None:
        raise StoreError("no triage proposal to reject")
    store.append_event(
        incident_id,
        _event(actor, "triage_rejected", rationale, payload={"rationale": rationale}),
    )
    return store.get_incident(incident_id)


def override_triage(
    store: Store,
    incident_id: str,
    actor: str,
    field: str,
    value: Any,
    rationale: str,
) -> Incident:
    validate_actor(actor)
    if not is_human_actor(actor):
        raise StoreError("override_triage requires a human actor")
    if field not in {"priority", "impact_score", "assigned_to"}:
        raise StoreError(f"cannot override field {field!r}")
    incident = store.get_incident(incident_id)
    previous = getattr(incident, field)
    store.append_event(
        incident_id,
        _event(
            actor,
            "human_override",
            rationale,
            payload={"field": field, "value": value, "previous": previous, "rationale": rationale},
        ),
    )
    store.emit_metric(incident_id, "human_override", 1, actor, labels={"field": field})
    return store.get_incident(incident_id)
