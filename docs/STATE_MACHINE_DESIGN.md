# Phase 1 State Machine Design

**Status**: Phase 1 implemented (slices 0–12 + handoff failsafe). Residual eval gaps in `PHASE1_EXIT.md`.  
**Scope**: Phase 1 Foundation ("The Verifiable Incident Brain")  
**Date**: 2026-05 (logging / zero-trust interlock 2026-08; handoff failsafe 2026-08-15)  
**Principles Applied**: Simplicity, First Principles, Zero Trust, Verifiability First, Human Authority + AI Agency, ample structured logging, readable by senior engineer in <5 minutes.  
**Interlocks**: `FIRST_PRINCIPLES.md` · `IMPLEMENTATION_PLAN.md` · `PHASE1_SUCCESS_CRITERIA.md` · `EVALUATION_RUBRIC.md`

## Goals of the Phase 1 State Machine

1. Own the **single source of truth** for every incident from first detection to closure.
2. Provide a clean, explicit, auditable lifecycle that maps to ITIL 4 outcomes without bureaucratic overhead.
3. Enable AI to do high-volume cognitive work (triage, impact assessment, communication drafting, detection gap identification) while requiring human approval on high-stakes transitions (**zero trust**: AI proposes; policy + gates accept).
4. Support continuous "living" artifacts (especially detection gap analysis and postmortem draft) that improve as the incident evolves.
5. Be trivially inspectable and replayable for evaluation.
6. Emit enough **structured events and metrics** that future performance dashboards and improvement analysis need only aggregation — not re-instrumentation.

## Core States (Minimal & Sufficient for Phase 1)

```python
from enum import Enum

class IncidentState(str, Enum):
    DETECTED      = "DETECTED"      # First signal received (alert, ticket, synthetic, user report)
    TRIAGING      = "TRIAGING"      # AI enriching context, assessing impact, noise reduction, routing
    ACKNOWLEDGED  = "ACKNOWLEDGED"  # Initial human/AI acknowledgment + communication sent
    ACTIVE        = "ACTIVE"        # Investigation + mitigation underway (humans + AI)
    RESOLVED      = "RESOLVED"      # Service restored + verification complete
    CLOSED        = "CLOSED"        # Final sign-off, learning captured, record locked
```

**Why these states (not 10-step literal mapping)?**
- They cover the entire user-provided flow while collapsing low-value distinctions.
- They create natural points for AI reasoning and human gates.
- `ACTIVE` is intentionally broad in Phase 1 (detailed investigation swarm comes in Phase 2).

The default table below is the Phase 1 profile. A company overrides it in `company.toml` (`[lifecycle]`); `can_transition` reads that table. Do not add a second state-machine framework.

## Transition Rules (Phase 1)

| From State     | To State       | Trigger Type          | AI Autonomy                  | Human Gate?          | Notes |
|----------------|----------------|-----------------------|------------------------------|----------------------|-------|
| DETECTED      | TRIAGING      | Automatic            | Full (starts immediately)   | No                   | Ingestion complete |
| TRIAGING      | ACKNOWLEDGED  | AI proposes          | High (drafts comms + triage) | Yes if High/Critical | Low/Medium may proceed with AI actor; missing priority fails closed |
| ACKNOWLEDGED  | ACTIVE        | Automatic            | Medium                      | No                   | Work begins |
| ACTIVE        | RESOLVED      | Human + AI agreement | Medium (suggests resolution) | Yes (verification)   | Service must be confirmed |
| RESOLVED      | CLOSED        | Human approval       | Low (summarizes learning)   | Yes (always)         | Highest impact gate |
| RESOLVED or CLOSED | ACTIVE   | Reopen               | Propose only                | Yes                  | Reopen only. Escalate is not a state. |

**Approval Philosophy (Human Authority + AI Agency + Zero Trust)**:
- AI can **always** propose a transition with full reasoning trace and confidence — proposals are **untrusted** until policy accepts them.
- High-impact transitions (Critical priority, moving to CLOSED, major external communications) **fail closed** without explicit human approval (`approved_by` set).
- Low-risk / high-confidence actions (enriching context, drafting initial ack, logging detection gaps) may auto-apply only when policy allows **and** a full audit event is written.
- Auto-apply (`Low`/`Medium` + `confidence ≥ 0.8`) skips **human wait**, not the Grok call, and not High/Critical / CLOSED / bounce / typed confirm. Blast radius is not graduated from a streak of being right.
- Illegal transitions are rejected by code; they never appear as half-written state.

## Core Data Model (Pydantic — Source of Truth)

All models use strict typing and will be the foundation for storage and AI structured outputs.

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from enum import Enum

class IncidentState(str, Enum): ...

# Actor is a single validated string: "ai:grok:<model>" or "human:<id>".
# No parallel ActorType enum (two fields that can disagree is a lie).

class IncidentEvent(BaseModel):
    id: str
    timestamp: datetime
    actor: str                          # "ai:grok:<model>" or "human:<id>" — never anonymous
    event_type: str                     # "triage_completed", "communication_drafted", "state_transition", "metric", "human_override", ...
    from_state: Optional[IncidentState]
    to_state: Optional[IncidentState]
    reasoning: str                      # Full or summarized AI trace / human note
    confidence: Optional[float] = Field(ge=0, le=1)
    artifacts: List[str] = []           # References to files, CMDB snapshots, ai_traces, etc.
    requires_approval: bool = False
    approved_by: Optional[str] = None
    # Optional structured payload for metrics / overrides (dashboard-ready later)
    payload: Optional[dict] = None      # e.g. {"metric": "time_to_triage_ms", "value": 1200}

class TriageResult(BaseModel):
    priority: Literal["Critical", "High", "Medium", "Low"]
    impact_score: int                   # 1-100 business impact
    affected_users_estimate: int
    affected_services: List[str]
    category: str
    routing_suggestion: str
    duplicate_of: Optional[str] = None
    reasoning: str
    confidence: float

class CommunicationDraft(BaseModel):
    audience: Literal["internal", "customers", "leadership"]
    channel: str
    subject: str
    body: str
    tone: str
    expected_resolution_window: Optional[str]
    confidence: float

class DetectionGap(BaseModel):
    gap_description: str
    evidence: str
    suggested_monitoring_or_runbook_change: str
    severity: Literal["High", "Medium", "Low"]
    discovered_during: str              # "triage", "investigation", "post-incident"

class Incident(BaseModel):
    id: str
    title: str
    current_state: IncidentState
    created_at: datetime
    updated_at: datetime

    # Core classification (updated over time)
    priority: Optional[str] = None
    impact_score: Optional[int] = None

    # Rich context (enriched continuously)
    reporter: str
    source: str                         # "datadog", "user_portal", "synthetic", ...
    affected_services: List[str] = []
    affected_ci_ids: List[str] = []  # primary first; CMDB tags, not display names
    cmdb_snapshot: dict = {}
    related_incidents: List[str] = []
    recent_changes: List[str] = []

    # Living artifacts (updated by AI + humans)
    timeline: List[IncidentEvent] = []
    communications: List[CommunicationDraft] = []
    detection_gaps: List[DetectionGap] = []
    ai_triage: Optional[TriageResult] = None

    # Resolution & learning
    resolution_notes: Optional[str] = None
    postmortem_draft: Optional[str] = None   # Continuously updated

    # Human oversight
    assigned_to: Optional[str] = None
    # Approvals live on IncidentEvent (approved_by). No untyped approvals list.
```

## Storage Approach (Phase 1)

- Primary: SQLite (`incidents.db`) with two tables:
  - `incidents` (current snapshot — fast queries)
  - `incident_events` (append-only audit log — full verifiability; includes metric events)
- Secondary artifact store: `incidents/{incident_id}/` folder containing:
  - `incident.json` (latest materialized view — **not** authoritative)
  - `raw_inputs/` (original alert payload, screenshots, logs — immutable once written)
  - `ai_traces/` (full prompt + raw response + parsed output + latency_ms for every Grok call)
- Optional process-wide: `runtime/metrics.jsonl` for cross-incident aggregation (same fields as metric events)
- This gives fast state + complete auditability + easy human inspection + feedstock for future dashboards.

### AI trace file minimum fields

```text
trace_id, incident_id, purpose, model, started_at, ended_at, latency_ms,
prompt, raw_response, parsed_ok, parsed_output | error, confidence (if any)
```

### Metrics to emit as events or JSONL (see FIRST_PRINCIPLES.md)

`time_to_triage_ms`, `time_to_first_ack_draft_ms`, `ai_call_latency_ms`, `ai_call_error`,
`ai_confidence`, `human_override`, `approval_wait_ms`, `duplicate_detected`,
`detection_gap_count`, `state_dwell_ms` — even when no UI consumes them yet.

## Verifiability & Replay Guarantees

- Every state change **must** be accompanied by an `IncidentEvent`.
- All AI outputs are stored with full reasoning and a dedicated trace file.
- The evaluation harness can replay any incident by feeding the same inputs + context to the system and comparing outputs.
- `incident.json` is a materialized view only — the event log is the source of truth.
- Human overrides are new events; they never silently rewrite prior events (append-only history).

## Human-in-the-Loop Surface Area (Phase 1)

The operator surface is `cli.py` (not a web API):
- Approve / Reject AI-proposed triage + add note (human actor id required; AI cannot approve)
- Override priority / impact / assigned_to (recorded as `human_override` with rationale)
- Add free-form observation (`note` → event)
- Human state change requires typed `--confirm` equal to the target state (failsafe, not gamification)
- `assign` / `release` / `route` are events. Support group cannot change without `support_group_changed` (from/to/reason/actor). Holder must `release` (type `RELEASE`) before another tech moves the incident, unless `--steal` with reason
- `propose` runs existing triage + ack/status drafts + gaps on one id. Drafts never send.

This design keeps the state machine as the governor while giving AI agency **inside** each state under zero-trust policy.

---

**Next**: Implementation follows `IMPLEMENTATION_PLAN.md`. Success Criteria and Evaluation Rubric must stay aligned with any change here.