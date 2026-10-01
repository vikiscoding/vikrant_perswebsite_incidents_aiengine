# First Principles, Zero Trust & Observability — Incident-AI

**Status:** Locked engineering constitution (inspiration only from general app-dev flywheel ideas — **this is not a separate flywheel product**)  
**Date:** 2026-08-11  
**Audience:** Anyone building or reviewing this repo  
**Interlocks:** `AGENTS.md` · `STATE_MACHINE_DESIGN.md` · `PHASE1_SUCCESS_CRITERIA.md` · `EVALUATION_RUBRIC.md` · `IMPLEMENTATION_PLAN.md`

---

## Purpose

We do **not** invent a meta-“flywheel system” for this project.  
We **do** borrow three hard disciplines from first-principles engineering and apply them directly to an AI-native incident OS:

1. **First principles** — start from irreducible facts of incident work, not process theater or agent fashion.  
2. **Zero trust** — never trust AI, inputs, or implicit authority; verify, constrain, and gate by blast radius.  
3. **Ample structured logging** — capture enough decision, performance, and outcome data that future improvement loops and dashboards are possible without re-instrumenting later.

These disciplines strengthen the existing product: state machine + SSOT + Grok proposals + evaluation. They do not replace it.

---

## 1. First Principles of Incident Work

Software that “manages incidents” must map reality:

| Irreducible fact | Design consequence |
|------------------|--------------------|
| Shared truth is the product | Event-sourced SSOT and a readable `incidents/{id}/` record beat chat summaries |
| Decision latency costs money and trust | Triage + ack path must be fast, explicit, and measurable |
| Wrong priority or lost context multiplies damage | Structured triage, enrichment, and handoff artifacts are core, not nice-to-have |
| Humans retain liability on high impact | AI proposes; humans approve high-blast-radius moves |
| Learning dies unless captured during the work | Living detection gaps + postmortem draft update continuously |
| LLMs are jagged proposers, not oracles | Deterministic state/schema/storage; Grok only where judgment is irreducible |

### Critical path (minimum sequence that must work)

```
signal in → validate & persist → establish SSOT record
  → triage / impact (AI propose, schema-validate)
  → communicate (AI draft, policy on send)
  → lifecycle transitions (rules + human gates)
  → resolution verified → close with learning captured
```

If this path is incomplete, non-replayable, or untrusted, later agents and dashboards are decoration.

### Questions every slice must answer before code

1. What is the **single most important output** of this slice?  
2. What is the **exact data flow** into the SSOT and event log?  
3. Which steps are **deterministic** (code/tests only)?  
4. Where is **irreducible uncertainty** (Grok may propose only here)?  
5. What is logged so we can **score, debug, and improve** later?

---

## 2. Zero Trust (Applied to Incident-AI)

Zero trust here means: **assume every input, model output, and implied permission is untrusted until verified against policy.**

### 2.1 Never trust by default

| Subject | Default stance | Verification |
|---------|----------------|--------------|
| External alerts / tickets / user reports | Untrusted | Schema validation, source tagging, raw payload retained under `raw_inputs/` |
| Grok structured outputs | Untrusted proposals | Pydantic parse; reject/repair path; confidence recorded; no silent coercion of illegal fields |
| AI-proposed state transitions | Untrusted until policy allows | Transition table + human gate for high impact |
| “Auto-send communication” | Untrusted | Draft-first; send only under explicit policy (Phase 1: draft + approve for high impact) |
| Materialized `incident.json` | Convenience view only | Event log is authoritative; rebuild view from events when in doubt |

### 2.2 Least privilege for AI

- AI may: enrich context, propose triage, draft comms, list detection gaps, suggest transitions.  
- AI may **not**: unilaterally set Critical without gate, close incidents, execute production mitigations (Phase 3+ and still gated), or rewrite history.  
- Low-risk actions may auto-apply only when confidence ≥ threshold **and** policy allows **and** a full audit event is written.

### 2.3 Explicit identity & provenance

Every event and AI call records:

- **Actor**: `human:<id>` or `ai:grok:<model>`  
- **Time** (UTC)  
- **Inputs referenced** (artifact paths, CMDB snapshot hash/id)  
- **Decision** + **reasoning**  
- **Confidence** when AI  
- **Approval** (required / granted / rejected / overridden) with human id when applicable  

No anonymous “system did something.”

### 2.4 Fail closed on high blast radius; degrade open on AI outage

- High impact (Critical priority, CLOSED, major external comms): **fail closed** without human approval.  
- Grok unavailable or confidence low: **degrade** to human-driven flow; keep SSOT healthy; mark AI fields incomplete — never invent silent defaults that look authoritative.

### 2.5 Continuous verification

- Illegal transitions cannot be written.  
- Eval harness replaying known fixtures is the acceptance test for cognitive features.  
- Human overrides are first-class events (not side-channel Slack fixes).

---

## 3. Ample Logging for Improvement Data & Future Dashboards

We do **not** build a full analytics product in Phase 1.  
We **do** log so that dashboards, coaching loops, and model improvement are cheap later.

### 3.1 Logging layers (all append-friendly)

| Layer | What | Where (Phase 1) |
|-------|------|------------------|
| **Domain events** | State transitions, approvals, overrides, artifacts linked | SQLite `incident_events` + timeline in `incident.json` |
| **AI traces** | Full prompt context, raw response, parsed model, latency_ms, tokens if available, model id, confidence | `incidents/{id}/ai_traces/{trace_id}.json` |
| **Performance / ops metrics** | Structured one-line or JSON metrics events | `incident_events` with `event_type=metric` **or** `metrics.jsonl` at repo/runtime root |
| **Evaluation scores** | Rubric dimensions, scorer notes, fixture id | `evaluations/{date}/` |
| **Raw inputs** | Immutable originals | `incidents/{id}/raw_inputs/` |

### 3.2 Metrics that must be cheap to emit from day one

Emit as structured fields (even if no UI consumes them yet):

| Metric | Why |
|--------|-----|
| `time_to_triage_ms` | Critical path latency |
| `time_to_first_ack_draft_ms` | Communication speed |
| `ai_call_latency_ms` / `ai_call_error` | Cost and reliability of Grok path |
| `ai_confidence` by decision type | Calibration and auto-approve policy |
| `human_override` (bool + field) | Where AI is wrong or untrusted |
| `approval_wait_ms` | Process friction |
| `duplicate_detected` | Noise reduction efficacy |
| `detection_gap_count` by severity | Learning signal |
| `state_dwell_ms` per state | Bottleneck analysis |
| `rubric_*` scores post-eval | Product quality over time |

These become the feedstock for later **performance dashboards** (MTTR proxies, override rates, confidence calibration, eval trendlines) without redesigning storage.

### 3.3 Logging rules (non-negotiable)

1. **Every Grok call** → complete, replayable trace file. No “fire and forget.”  
2. **Every state change** → `IncidentEvent` with actor + reasoning.  
3. **Prefer structured JSON** over free-text-only logs for anything we might chart.  
4. **Never log secrets** (API keys, tokens); redact if user paste includes them.  
5. **Append-only history** — corrections are new events, not silent edits to past events.  
6. **Human-readable on disk** — a senior engineer reconstructs the incident from the folder alone.

### 3.4 What “future dashboards” means (intentionally deferred UI)

Phase 1 ships **data**, not charts. When a dashboard is justified, it should only aggregate already-logged fields, e.g.:

- Eval score trends by dimension  
- Override rate by triage field  
- Distribution of AI confidence vs outcome quality  
- Time-in-state and time-to-ack  
- Detection gaps opened vs closed over time  

If a metric is not logged in the event/trace layer, we do not claim we can “add a dashboard later” for free.

---

## 4. Decision Rule: Deterministic vs Grok

**Default: deterministic.**

| Deterministic (code owns) | Grok may propose (then verify) |
|---------------------------|--------------------------------|
| State enum & legal transitions | Priority / impact judgment |
| Persistence, IDs, timestamps | Routing narrative, duplicate *judgment* |
| Who must approve | Comms body/tone |
| Schema validation | Detection gap insight |
| Metric emission, file layout | Optional enrichment summaries |

Promote an AI-backed behavior only when the eval rubric shows improvement (or non-regression) on the fixed fixture set — not because a demo looked good.

**The sounder system is the one already built**: Grok proposes, code gates, humans own blast radius, eval scores from outside. Do not add a second loop that watches those scores and moves the gate.

**Cost of a Grok call is physics, not a product.** Default is still deterministic. Do not invent a “determinism thermostat,” proof-matching engine, or model-that-decides-whether-to-call-the-model.

The only legal way to spend fewer tokens:

1. **Do not ask twice.** If no new events/inputs since the last successful call for that purpose, reuse the last trace. `propose` is not a license to re-tax the same question.
2. **Code already knows.** Same open CI + same monitor in the window → duplicate attach, no new triage. CMDB `routing_hint` is a fact; Grok may narrate, not invent a second CMDB.
3. **Shadow, then cut, then revert.** A rule may run *beside* Grok and log agree/disagree (`human_override`, live eval floors, routing match). Skip the call only after a boring agreement stream on **Low blast** only. If override rate or eval floors break, turn the call back on the same day. Fail toward more model + more human, not less.
4. **Blast radius is not a statistic you graduate from.** Critical, CLOSED, bounce (`work_done` / `why_not_us`), typed confirm, external send — always gated. A long streak of being right does not buy a skip.

Human time on the bridge is more expensive than tokens. Saving four calls and dumping context is a loss. Calibrate `AUTO_APPLY_MIN_CONFIDENCE` (today `0.8`, Low/Medium only) from the live eval batch — that saves *approvals*, not API calls.

Decision, 2026-08-15: do not build this before the live batch exists. The stream is the input; the thermostat is not.

---

## 5. Acceptance Test for Any Change

Accept a change only if it improves at least one of:

- Correctness or completeness of the **SSOT critical path**, or  
- **Trust** (stricter gates, better provenance, fewer illegal paths), or  
- **Verifiability / replay**, or  
- **Log completeness** for future improvement and dashboards, or  
- **Rubric outcomes** on the evaluation set,

…without a larger penalty elsewhere (complexity, opacity, missing traces).

Reject: speculative agent frameworks, multi-model sprawl, dashboard UIs before reliable logs, Phase 2+ investigation before Phase 1 exit criteria, a reliability/determinism product that moves gates from scores.

---

## 6. Document Map

| Document | Role |
|----------|------|
| `AGENTS.md` | Project rules & mission (includes these principles by reference) |
| `FIRST_PRINCIPLES.md` | This file — FP, zero trust, logging constitution |
| `STATE_MACHINE_DESIGN.md` | Lifecycle, models, storage, gates |
| `PHASE1_SUCCESS_CRITERIA.md` | Done definition for foundation |
| `EVALUATION_RUBRIC.md` | How cognitive quality is scored |
| `IMPLEMENTATION_PLAN.md` | Ordered build slices with logging/zero-trust baked in |

**Delete process theater. Keep the record honest. Log enough to get smarter.**
