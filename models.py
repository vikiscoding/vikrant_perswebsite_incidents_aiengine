from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from company import get_company

AI_ACTOR_PREFIX = "ai:grok:"
HUMAN_ACTOR_PREFIX = "human:"
# Machine intake (e.g. vikrantsingh.fyi's heartbeat). Accepted ONLY to ingest an alert: the creation event and its
# metric. Transitions, approvals and handoffs keep validate_actor, so a service can never move or approve anything.
SERVICE_ACTOR_PREFIX = "service:"
SERVICE_EVENT_TYPES = frozenset({"incident_created", "metric"})
_FORBIDDEN_ACTORS = {"", "system", "admin"}

Priority = Literal["Critical", "High", "Medium", "Low"]


def is_human_actor(actor: str) -> bool:
    return isinstance(actor, str) and actor.startswith(HUMAN_ACTOR_PREFIX) and len(actor) > len(HUMAN_ACTOR_PREFIX)


def is_ai_actor(actor: str) -> bool:
    return isinstance(actor, str) and actor.startswith(AI_ACTOR_PREFIX) and len(actor) > len(AI_ACTOR_PREFIX)


def is_service_actor(actor: str) -> bool:
    return isinstance(actor, str) and actor.startswith(SERVICE_ACTOR_PREFIX) and len(actor) > len(SERVICE_ACTOR_PREFIX)


def validate_intake_actor(actor: str) -> str:
    """Ingest only: 'service:<name>' in addition to the human and AI actors."""
    if isinstance(actor, str) and is_service_actor(actor.strip()):
        return actor.strip()
    return validate_actor(actor)


def validate_actor(actor: str) -> str:
    if not isinstance(actor, str) or actor.strip() in _FORBIDDEN_ACTORS:
        raise ValueError("actor must be 'ai:grok:<model>' or 'human:<id>'; never empty, 'system', or 'admin'")
    actor = actor.strip()
    if is_human_actor(actor) or is_ai_actor(actor):
        return actor
    raise ValueError("actor must be 'ai:grok:<model>' or 'human:<id>'")


def _build_incident_state_enum() -> type[Enum]:
    states = get_company().states
    return Enum("IncidentState", {name: name for name in states}, type=str)


IncidentState = _build_incident_state_enum()


class IncidentEvent(BaseModel):
    id: str
    timestamp: datetime
    actor: str
    event_type: str
    from_state: Optional[IncidentState] = None
    to_state: Optional[IncidentState] = None
    reasoning: str
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    artifacts: List[str] = Field(default_factory=list)
    requires_approval: bool = False
    approved_by: Optional[str] = None
    payload: Optional[dict] = None

    @field_validator("actor")
    @classmethod
    def _actor_must_be_identified(cls, value: str) -> str:
        return validate_intake_actor(value)

    @model_validator(mode="after")
    def _service_actor_only_for_intake(self) -> "IncidentEvent":
        if is_service_actor(self.actor) and self.event_type not in SERVICE_EVENT_TYPES:
            raise ValueError(f"service actor may only record {sorted(SERVICE_EVENT_TYPES)}, not {self.event_type!r}")
        return self

    @field_validator("approved_by")
    @classmethod
    def _approved_by_must_be_human(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        identified = validate_actor(value)
        if not is_human_actor(identified):
            raise ValueError("approved_by must be 'human:<id>'")
        return identified


class TriageResult(BaseModel):
    priority: Priority
    impact_score: int = Field(ge=1, le=100)
    affected_users_estimate: int
    affected_services: List[str]
    category: str
    routing_suggestion: str
    duplicate_of: Optional[str] = None
    reasoning: str
    confidence: float = Field(ge=0, le=1)


class CommunicationDraft(BaseModel):
    audience: Literal["internal", "customers", "leadership"]
    channel: str
    subject: str
    body: str
    tone: str
    expected_resolution_window: Optional[str] = None
    confidence: float = Field(ge=0, le=1)


class DetectionGap(BaseModel):
    gap_description: str
    evidence: str = Field(min_length=1)
    suggested_monitoring_or_runbook_change: str
    severity: Literal["High", "Medium", "Low"]
    discovered_during: str
    status: Literal["proposed", "confirmed", "rejected"] = "proposed"


class DetectionGapBatch(BaseModel):
    gaps: List[DetectionGap]
    confidence: float = Field(ge=0, le=1)


class Incident(BaseModel):
    id: str
    title: str
    current_state: IncidentState
    created_at: datetime
    updated_at: datetime
    priority: Optional[Priority] = None
    impact_score: Optional[int] = Field(default=None, ge=1, le=100)
    reporter: str
    source: str
    affected_services: List[str] = Field(default_factory=list)
    affected_ci_ids: List[str] = Field(default_factory=list)
    cmdb_snapshot: dict = Field(default_factory=dict)
    related_incidents: List[str] = Field(default_factory=list)
    recent_changes: List[str] = Field(default_factory=list)
    timeline: List[IncidentEvent] = Field(default_factory=list)
    communications: List[CommunicationDraft] = Field(default_factory=list)
    detection_gaps: List[DetectionGap] = Field(default_factory=list)
    ai_triage: Optional[TriageResult] = None
    resolution_notes: Optional[str] = None
    postmortem_draft: Optional[str] = None
    assigned_to: Optional[str] = None
    support_group: Optional[str] = None
