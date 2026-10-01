# Phase 1 Success Criteria

**Version**: 0.2  
**Aligned to**: AGENTS.md Phase 1 — "The Verifiable Incident Brain"  
**Also aligned to**: `FIRST_PRINCIPLES.md` · `IMPLEMENTATION_PLAN.md` · `STATE_MACHINE_DESIGN.md` · `EVALUATION_RUBRIC.md`  
**Review Trigger**: When any of the core capabilities below are implemented or when the state machine changes.

## Overall Phase 1 Objective

Build a reliable, auditable foundation that owns the complete incident lifecycle as a single source of truth and uses Grok to eliminate the highest-pain cross-cutting problems from the traditional 10-step process:

- No single source of truth / lost context
- Alert fatigue + poor triage
- Late or missing acknowledgment and communication
- Detection gaps that are never identified
- Knowledge and learning that evaporates after resolution
- Blind trust in AI or unlogged decisions that cannot be improved later

## Mandatory Success Criteria (Must Pass Before Phase 2)

### 1. State Machine & Single Source of Truth
- The system can ingest an incident from at least 2 different sources (e.g., mock alert + manual report) and maintain a complete, queryable record across all 6 states.
- Every state transition is recorded as a verifiable `IncidentEvent` with actor, reasoning, timestamp, and confidence (when AI).
- A human can open any `incidents/{id}/` directory and fully reconstruct what happened and why the system made every decision without needing to run code.
- **Success Threshold**: 100% of test incidents have complete event logs with no missing transitions.

### 2. Intelligent Ingestion + Triage (Highest Leverage Early Win)
- AI produces a `TriageResult` (priority, impact_score 1-100, affected users estimate, category, routing, duplicate detection) with traceable reasoning.
- Raw inputs are schema-validated and stored immutably under `raw_inputs/` (zero trust on external signals).
- Triage quality is scored using the Phase 1 Evaluation Rubric.
- **Minimum Target on Evaluation Set** (first 8–10 historical or synthetic incidents):
  - Average triage rubric score ≥ 3.8 / 5.0
  - At least 70% of incidents receive "correct or better" priority + impact within 20% of ground truth
  - Duplicate detection works on at least 1 obvious duplicate case

### 3. Automated Communication Layer
- System generates high-clarity initial acknowledgment + at least one status update draft using the `CommunicationDraft` model.
- Communications are appropriate for audience (internal vs customers) and set reasonable expectations.
- Phase 1 may draft-only (no live send) as long as drafts are first-class artifacts with events.
- **Success Threshold**: Average communication clarity score ≥ 4.0 / 5.0 on rubric across evaluation incidents. No major factual errors or tone issues.

### 4. Living Detection Gap Analysis (Signature Phase 1 Capability)
- The system identifies and records at least one meaningful `DetectionGap` on the majority of evaluation incidents (even if humans previously missed it).
- Gaps require an evidence field and are linked to concrete suggested improvements (monitoring, runbook, CMDB, etc.).
- **Success Threshold**: On the first 8–10 evaluation incidents, the system surfaces ≥ 5 total high/medium severity detection gaps that were not obvious in the raw data.

### 5. Verifiability, Auditability & AI Traces
- For every Grok call made during an incident, the full prompt context, model response, latency, and reasoning used for decisions are stored in `ai_traces/`.
- The evaluation harness can replay any incident and produce comparison of outputs against ground truth.
- **Success Threshold**: 100% of AI decisions on evaluation incidents have full replayable traces.

### 6. Human-in-the-Loop Mechanics (Zero Trust Gates)
- The system can propose state transitions and require explicit human approval for high-impact moves (e.g., Critical priority, moving to CLOSED).
- A human can override any AI output and the override is captured as an event with actor + rationale (append-only).
- High-impact actions **fail closed** without approval.
- **Success Threshold**: All high-impact transitions in the evaluation set correctly surface for approval; no path bypasses the gate in tests.

### 7. Structured Logging & Future Dashboard Readiness
- Structured metrics defined in `FIRST_PRINCIPLES.md` §3.2 are emitted for the Phase 1 critical path (at minimum: time_to_triage, ai_call_latency, human_override, detection_gap_count, state transitions with timestamps).
- Logs are machine-parseable (events payload and/or `metrics.jsonl`) and free of secrets.
- **Success Threshold**: After a full lifecycle demo, a simple script or manual parse can extract those metrics without reading free-text-only logs. No dashboard UI is required in Phase 1.

### 8. Foundational Engineering Quality
- The entire Phase 1 codebase + data model is understandable by a senior engineer in under 5 minutes (self-assessment + peer review).
- No speculative agent frameworks. SQLite + clean Pydantic + direct Grok calls only.
- All code follows `AGENTS.md` and `FIRST_PRINCIPLES.md` (simplicity, zero trust, surgical changes, verifiability).
- Implementation order tracked against `IMPLEMENTATION_PLAN.md` (deviations documented in `PHASE1_EXIT.md`).

## Stretch Goals (Nice to Have in Phase 1)

- Continuous updating of `postmortem_draft` as new information arrives (not just at the end).
- Automatic enrichment of CMDB + recent changes context with >80% accuracy on evaluation set.
- Early warning of potential SLA breach based on current state + historical patterns (even simple heuristics).
- Lightweight offline HTML or notebook that charts already-logged metrics (still not a product dashboard).

## Exit Criteria for Phase 1

Phase 1 is considered complete and ready for Phase 2 work only when:

1. All **8** Mandatory Success Criteria are met on a minimum of 10 evaluation incidents (mix of real historical + high-quality synthetic).
2. A clean demo exists showing one full incident lifecycle from detection through closure with rich AI-generated artifacts and human approval steps.
3. Evaluation scores and traces are published (even internally) so progress is visible and credible.
4. The state machine and data model have survived at least one round of real dogfooding or realistic replay without major redesign.
5. Metric/event logs from that demo are sufficient to answer: time-to-triage, whether humans overrode AI, and how many detection gaps were raised — without re-running the system.

## Measurement Approach

- Primary: Structured rubric scoring (see `EVALUATION_RUBRIC.md`)
- Secondary: Logged operational metrics (latency, overrides, confidence) — feedstock for future dashboards
- Tertiary: Qualitative engineer feedback on cognitive load and context quality
- Artifact quality: Side-by-side comparison of system-generated record vs historical human-only record for the same incident

---

**Important**: These criteria are deliberately ambitious but narrow. We are not trying to solve investigation or automated remediation in Phase 1. We are building the trustworthy, logged foundation that makes later phases and improvement loops possible.

Reducing API spend or “verification volume” is **not** a Phase 1 success criterion. The live eval batch exists to measure cognitive quality. After it, we may skip *redundant* questions (same propose, obvious duplicate). We do not move gates because the graph was green.