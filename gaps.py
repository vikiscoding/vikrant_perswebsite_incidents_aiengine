import json
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from grok import GrokClient
from models import DetectionGap, DetectionGapBatch, Incident, IncidentEvent, is_human_actor, validate_actor
from store import Store, StoreError, _utcnow

GapStatus = Literal["proposed", "confirmed", "rejected"]


@dataclass
class GapsOutcome:
    incident: Incident
    added: list[DetectionGap]
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


def gap_key(description: str) -> str:
    return description.strip().lower()


def _prompt(incident: Incident, discovered_during: str) -> str:
    existing = [
        {"description": gap.gap_description, "status": gap.status, "severity": gap.severity}
        for gap in incident.detection_gaps
    ]
    context = {
        "title": incident.title,
        "state": incident.current_state.value if hasattr(incident.current_state, "value") else str(incident.current_state),
        "source": incident.source,
        "affected_services": incident.affected_services,
        "affected_ci_ids": incident.affected_ci_ids,
        "cmdb_snapshot": incident.cmdb_snapshot,
        "triage": incident.ai_triage.model_dump(mode="json") if incident.ai_triage else None,
        "existing_gaps": existing,
        "discovered_during": discovered_during,
    }
    return (
        "Find detection gaps: missing monitors, runbooks, CMDB links, or alerts that would have caught this earlier.\n"
        "Each gap MUST include a non-empty evidence string grounded in this incident. No evidence = do not include it.\n"
        "Do not repeat existing_gaps. Do not invent tools we do not have.\n"
        "suggested_monitoring_or_runbook_change must be concrete.\n"
        "confidence is required (0 to 1) for the batch.\n\n"
        f"{json.dumps(context, default=str)}"
    )


def _emit_counts(store: Store, incident_id: str, actor: str, gaps: list[DetectionGap]) -> None:
    live = [gap for gap in gaps if gap.status != "rejected"]
    for severity in ("High", "Medium", "Low"):
        store.emit_metric(
            incident_id,
            "detection_gap_count",
            sum(1 for gap in live if gap.severity == severity),
            actor,
            labels={"severity": severity},
        )


def analyze_gaps(
    store: Store,
    grok: GrokClient,
    incident_id: str,
    discovered_during: str = "triage",
) -> GapsOutcome:
    incident = store.get_incident(incident_id)
    actor = _actor_ai(grok)
    result = grok.complete_structured(
        _prompt(incident, discovered_during),
        DetectionGapBatch,
        incident_id=incident_id,
        purpose=f"detection_gaps_{discovered_during}",
    )
    if not result.ok or not result.parsed:
        store.append_event(
            incident_id,
            _event(actor, "detection_gaps_failed", result.error or "gaps parse failed", payload={"error": result.error}),
        )
        return GapsOutcome(
            incident=store.get_incident(incident_id),
            added=[],
            error=result.error or "detection gap analysis failed",
            trace_path=result.trace_path,
        )

    batch = DetectionGapBatch.model_validate(result.parsed)
    known = {gap_key(gap.gap_description) for gap in incident.detection_gaps}
    added: list[DetectionGap] = []
    for raw in batch.gaps:
        if not raw.evidence.strip():
            continue
        key = gap_key(raw.gap_description)
        if key in known:
            continue
        gap = raw.model_copy(update={"discovered_during": discovered_during, "status": "proposed"})
        added.append(gap)
        known.add(key)

    if added:
        store.append_event(
            incident_id,
            _event(
                actor,
                "detection_gaps_proposed",
                f"proposed {len(added)} detection gap(s)",
                confidence=batch.confidence,
                artifacts=[result.trace_path] if result.trace_path else [],
                payload={"gaps": [gap.model_dump(mode="json") for gap in added]},
            ),
        )
        _emit_counts(store, incident_id, actor, store.get_incident(incident_id).detection_gaps)

    return GapsOutcome(
        incident=store.get_incident(incident_id),
        added=added,
        error=None,
        trace_path=result.trace_path,
    )


def set_gap_status(store: Store, incident_id: str, actor: str, description: str, status: GapStatus) -> Incident:
    validate_actor(actor)
    if not is_human_actor(actor):
        raise StoreError("gap status changes require a human actor")
    if status not in {"proposed", "confirmed", "rejected"}:
        raise StoreError(f"invalid gap status {status!r}")
    key = gap_key(description)
    incident = store.get_incident(incident_id)
    if not any(gap_key(gap.gap_description) == key for gap in incident.detection_gaps):
        raise StoreError("unknown detection gap")
    store.append_event(
        incident_id,
        _event(actor, "detection_gap_status", f"gap {status}", payload={"key": key, "status": status}),
    )
    return store.get_incident(incident_id)
