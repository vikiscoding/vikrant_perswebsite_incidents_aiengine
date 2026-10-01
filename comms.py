import json
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from grok import GrokClient
from models import CommunicationDraft, Incident, IncidentEvent
from store import Store, StoreError, _ms_since, _utcnow

DraftKind = Literal["ack", "status"]
Audience = Literal["internal", "customers", "leadership"]


@dataclass
class CommsOutcome:
    incident: Incident
    draft: Optional[CommunicationDraft]
    kind: DraftKind
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


def _has_ack(incident: Incident) -> bool:
    return any(
        event.event_type == "communication_drafted" and (event.payload or {}).get("kind") == "ack"
        for event in incident.timeline
    )


def _prompt(incident: Incident, kind: DraftKind, audience: Audience) -> str:
    context = {
        "kind": kind,
        "audience": audience,
        "title": incident.title,
        "state": incident.current_state.value if hasattr(incident.current_state, "value") else str(incident.current_state),
        "priority": incident.priority,
        "impact_score": incident.impact_score,
        "affected_services": incident.affected_services,
        "affected_ci_ids": incident.affected_ci_ids,
        "routing": (incident.cmdb_snapshot or {}).get("routing_hint"),
        "triage_reasoning": incident.ai_triage.reasoning if incident.ai_triage else None,
    }
    job = (
        "Write the initial acknowledgment. Confirm we are aware, say what is affected, "
        "and set a cautious expectation. Do not promise a fix time you cannot know."
        if kind == "ack"
        else "Write a status update. Say what we know now, what we are doing, and what is still unknown. Do not invent a root cause."
    )
    tone = {
        "internal": "direct, operational, no marketing",
        "customers": "plain language, calm, no internal CI ids unless needed",
        "leadership": "short, impact-first, no jargon",
    }[audience]
    return (
        f"{job}\n"
        f"audience={audience}. tone={tone}.\n"
        "Return a CommunicationDraft. channel should be slack for internal, status_page for customers, email for leadership.\n"
        "confidence is required (0 to 1). This is a draft only; it will not be sent.\n\n"
        f"{json.dumps(context, default=str)}"
    )


def draft_communication(
    store: Store,
    grok: GrokClient,
    incident_id: str,
    kind: DraftKind,
    audience: Audience,
) -> CommsOutcome:
    if kind not in {"ack", "status"}:
        raise StoreError(f"unknown draft kind {kind!r}")
    incident = store.get_incident(incident_id)
    actor = _actor_ai(grok)
    result = grok.complete_structured(
        _prompt(incident, kind, audience),
        CommunicationDraft,
        incident_id=incident_id,
        purpose=f"comms_{kind}_{audience}",
    )
    if not result.ok or not result.parsed:
        store.append_event(
            incident_id,
            _event(actor, "communication_failed", result.error or "comms parse failed", payload={"kind": kind, "error": result.error}),
        )
        return CommsOutcome(
            incident=store.get_incident(incident_id),
            draft=None,
            kind=kind,
            error=result.error or "communication draft failed",
            trace_path=result.trace_path,
        )

    draft = CommunicationDraft.model_validate(result.parsed)
    if draft.audience != audience:
        draft = draft.model_copy(update={"audience": audience})

    first_ack = kind == "ack" and not _has_ack(incident)
    store.append_event(
        incident_id,
        _event(
            actor,
            "communication_drafted",
            f"{kind} draft for {audience}",
            confidence=draft.confidence,
            artifacts=[result.trace_path] if result.trace_path else [],
            payload={"kind": kind, "draft": draft.model_dump(mode="json"), "sent": False},
        ),
    )
    if first_ack:
        store.emit_metric(
            incident_id,
            "time_to_first_ack_draft_ms",
            _ms_since(incident.created_at, _utcnow()),
            actor,
            labels={"audience": audience},
        )
    return CommsOutcome(
        incident=store.get_incident(incident_id),
        draft=draft,
        kind=kind,
        error=None,
        trace_path=result.trace_path,
    )


def draft_ack_and_status(store: Store, grok: GrokClient, incident_id: str) -> tuple[CommsOutcome, CommsOutcome]:
    ack = draft_communication(store, grok, incident_id, "ack", "customers")
    status = draft_communication(store, grok, incident_id, "status", "internal")
    return ack, status
