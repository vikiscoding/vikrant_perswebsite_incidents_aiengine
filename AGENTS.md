# Incident-AI — Project Rules

## Mission

**Long-term aim:** an incident management system that delivers ITIL 4-aligned outcomes faster and more consistently than human-only processes, with people in authority on every decision that matters.

**Today:** a working incident record and triage agent for one operator, live on one small site. Build toward the aim one verified slice at a time; never describe the aim as if it were shipped.

The system owns the single source of truth for every incident, drives the full lifecycle (Detection → Identification → Triage → Investigation → Mitigation → Resolution → Closure + Continuous Learning), automates the maximum possible cognitive load and coordination work using Grok, and keeps humans in clear authority on high-stakes decisions.

It should keep a complete record of every incident, flag detection gaps as the incident unfolds, and close the feedback loops that usually break in human-only processes (alert fatigue, lost context, late or missing postmortems, knowledge staying in people’s heads).

We deliberately build a **verifiable core first**: a clean state machine + persistent memory + real-time reasoning layer. Specialist agent capabilities (parallel hypothesis investigation, automated mitigation suggestions, etc.) are added only after the foundation is reliable, auditable, and demonstrably valuable on real incidents.

## Core Principles (Non-Negotiable)

- **Simplicity First**: Minimum code and structure that delivers the outcome. No speculative multi-agent frameworks, no “future-proof” abstractions, no over-engineering. Prefer boring, inspectable code.
- **First Principles**: Design from the irreducible facts of incident work (shared truth, decision latency, blast radius, human liability). Do not invent meta-products (e.g. a separate “flywheel engine” or a reliability/determinism thermostat). The shipped propose → gate → log → eval loop *is* the control system. See `docs/FIRST_PRINCIPLES.md` §4.
- **Zero Trust**: Never trust raw inputs or AI outputs by default. Schema-validate everything; treat Grok as a proposer; fail closed on high-blast-radius actions; require explicit actor provenance on every decision. See `docs/FIRST_PRINCIPLES.md`.
- **Verifiability First**: Every AI decision, hypothesis, or action must be traceable, explainable, and replayable. No black boxes. Every Grok call is logged with full context, prompt, output, latency, and confidence.
- **Ample Structured Logging**: Domain events, AI traces, and performance metrics are first-class. Log enough for future improvement analysis and performance dashboards **without** building dashboard UI in Phase 1. Append-only history; no silent rewrites. See `docs/FIRST_PRINCIPLES.md` §3.
- **Human Authority, AI Agency**: AI proposes, executes only low-risk / high-confidence actions under policy, surfaces signal, and maintains perfect context. Humans retain final authority on priority, high-impact changes, and escalations. Clear, explicit handoff points at all times.
- **Surgical Changes Only**: Touch only what is required. Match existing style and structure exactly. Never refactor unrelated code.
- **Think Before Coding**: State assumptions explicitly. Surface tradeoffs and risks. Ask when anything is unclear.
- **Goal-Driven Execution + Evaluation as Product**: Every task has clear success criteria and measurable rubrics before work begins. Evaluation harness and scoring are first-class deliverables, not afterthoughts.
- **Learning From Real Work**: Real incidents + high-quality synthetic replays + logged outcomes continuously improve the system. Improvement comes from data we already collected — not from a separate flywheel product. A long clean streak does not buy a weaker gate.
- **ITIL as Constitution, Not Bureaucracy**: Use the spirit and outcomes of ITIL 4 (restore service quickly, minimize business impact, collaborate, learn systematically, optimize and automate) while ruthlessly eliminating process friction through intelligent automation.

## Architecture & Tech Constraints

- **Core**: Monolithic Python application with a clean, inspectable, event-sourced state machine. Each incident is a first-class, persistent, queryable entity.
- **File Structure**: Keep it flat and obvious. No deep nesting. The entire control flow and reasoning logic must be understandable by a senior engineer in under 5 minutes.
- **State & Memory**: SQLite as the primary store for incident state, event log, decisions, and artifacts (one directory per incident under `incidents/{incident_id}/`). Simple schema + event log first. Postgres + pgvector only after the core is proven.
- **LLM**: Exclusively Grok via the xAI OpenAI-compatible endpoint. No other models.
- **Reasoning Style**: Heavy use of structured outputs (Pydantic). Multi-step reasoning and tool use are allowed only when wrapped in strong verification, evidence checking, and audit trails. Prefer deterministic scaffolding + Grok over free-form agent loops.
- **Output & Artifacts**: Every incident produces a complete, living record (timeline, decisions with rationale, hypotheses tested, communications, detection gap analysis, resolution notes, links to related records). This record is the single source of truth.
- **Telemetry**: Emit structured metrics (latency, confidence, overrides, state dwell, gap counts) as events or JSONL from day one so later dashboards only aggregate existing data.
- **Human Interface**: Start minimal (CLI + simple scriptable interface). Any UI later must make the underlying state/decision trace completely transparent.
- **Reliability**: The incident system itself must be more reliable than the systems it monitors. Graceful degradation when AI confidence is low or the model is unavailable.

## Development & Evaluation Workflow

- Follow `docs/IMPLEMENTATION_PLAN.md` slice order unless there is a documented reason to deviate.
- Evaluation is sacred and continuous. A replayable evaluation harness (historical incidents + synthetic scenarios with known ground truth) must exist and be the primary way progress is measured.
- Every significant capability is scored on explicit rubrics: triage accuracy + impact assessment, quality and verification of hypotheses, communication clarity and timeliness, detection gap identification, context preservation during handoffs, overall time-to-resolution/value, and human cognitive load reduction.
- Make changes → run the minimal harness → review full decision traces and scores → only then expand.
- Dogfood aggressively on real (or highly representative) incidents before claiming any capability is ready.
- No feature is “done” until it demonstrably improves outcomes on the evaluation set or real incidents versus the previous baseline (human-only or prior system state), **and** leaves complete logs/traces for that path.

## Product Direction & Phasing (Ruthless Prioritization)

The 10-step ITIL flow + cross-cutting problems (alert fatigue, lost context, late/no postmortems, knowledge evaporation, cognitive load, SLA blindness) are the target. We do **not** build 10 separate features. We build the high-leverage substrate that makes the entire flow dramatically better.

**Phase 1 – Foundation (shipped with residual gaps; current focus is live eval and the live incident desk, not Phase 2)**: The Verifiable Incident Brain
- Persistent, event-sourced state machine that owns the complete lifecycle and single source of truth.
- Intelligent ingestion + real-time triage (noise reduction, accurate impact assessment, correct categorization/priority/routing, duplicate detection).
- Automated context enrichment (pull CMDB, recent changes, related incidents, known errors).
- Always-on communication layer (initial acknowledgment, status updates, stakeholder notifications) with clear, accurate expectations.
- Living postmortem + detection gap analysis that updates continuously as new information arrives (the highest-leverage learning artifact).
- Clean human-in-the-loop gates with full visibility into AI reasoning.
- Structured metrics and full AI traces so improvement data and future performance dashboards are possible without re-instrumentation.

This single foundation directly attacks the worst cross-cutting problems: no single source of truth, alert fatigue, lost context on escalation, late or missing learning, and human bias/fatigue in triage and communication.

**Phase 2**: Verified parallel investigation (multiple hypotheses generated and evidence-checked in parallel, with explicit uncertainty handling). Not an unsupervised agent swarm.
**Phase 3**: Safe, auditable mitigation suggestions + runbook execution with approval gates that tighten over time.
**Phase 4**: Advanced systemic learning (automatic problem record creation, knowledge base updates, predictive signals, runbook improvement) fed by the logs and evals already in place.

Success metrics (Phase 1 and beyond):
- % of incidents with high-quality automated triage, impact assessment, and initial communication (target: >80% of routine + many major incidents).
- Measurable reduction in MTTR and engineer cognitive load on dogfooded incidents.
- Detection gaps and systemic issues surfaced that humans previously missed.
- Quality and timeliness of living postmortem artifacts vs historical baseline.
- SLA/OLA compliance with early warning.
- Engineer sentiment: “this actually reduces my stress and makes me better.”
- Operational: override rates, confidence calibration, time-to-triage/ack — from logged metrics, not anecdotes.

## Important Context

This project began as a broad multi-agent vision and was correctly narrowed to a high-quality Postmortem Agent to achieve technical reliability and quick wins. The current scope widens that to the incident lifecycle, with the same discipline around verifiability, evaluation, simplicity, and dogfooding.

The differentiator is the combination, not any one part: model reasoning, a verifiable state machine, a human gate, and honest logs on real incidents.

We stay narrow within each phase, ship working slices that deliver obvious value, measure ruthlessly, and only expand when the current foundation is solid. The goal is a system that is technically sound, operationally credible, and genuinely useful for one of the highest-pain, highest-leverage processes in any technology organization.

**Document map**: `docs/FIRST_PRINCIPLES.md` (FP + zero trust + logging) · `docs/IMPLEMENTATION_PLAN.md` (build order) · `docs/STATE_MACHINE_DESIGN.md` · `docs/PHASE1_SUCCESS_CRITERIA.md` · `docs/EVALUATION_RUBRIC.md` · `docs/PHASE1_EXIT.md` (sign-off + residual gaps) · `SITE_BRIDGE.md` (live incident desk) · `docs/proposals/HANDOFF_PING.md` (proposal: always-on bounce card) · `docs/proposals/BRIDGE_STANDOWN.md` (proposal: IM leave-code).

Consistent guidance: First principles over process theater. Zero trust over blind automation. Verifiability over magic. Evaluation and real outcomes over demos. Log enough to improve. Keep it simple enough for one person to build, understand, and evolve into something world-class.
