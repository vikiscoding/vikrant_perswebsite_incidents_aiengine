# Incident-AI

> **Live:** this repo runs the incident desk behind [vikrantsingh.fyi](https://vikrantsingh.fyi/reliability/): real site alerts, AI-proposed triage, human-gated lifecycle in GitHub Issues. See [SITE_BRIDGE.md](SITE_BRIDGE.md). Imported fresh from `itsm-incident-mgmt-agent@895b805` (code only, no incident data).

An incident triage agent with a human gate. An alert comes in and is stored as a folder that *is* the ticket; the model proposes priority, routing and draft updates; a person decides every step that matters; and every model call is traced. If the model is down, the ticket still exists and a person finishes the job.

Today it is a working incident record for one operator, not a production incident platform. It handles the real alerts of one small site ([live](https://vikrantsingh.fyi/reliability/#incident-desk)), and on that live desk the model never sets priority on its own: every proposal waits for a human `/approve`. Paging never depends on the model; it comes from an outside probe on the site's SLO.

## Current Focus: Phase 1 — The Verifiable Incident Brain

We are deliberately **not** building a full multi-agent swarm on day one.

**Phase 1** builds the trustworthy foundation:

- A clean, auditable state machine that owns the complete incident lifecycle as the single source of truth
- Grok-powered intelligent ingestion and triage (noise reduction, real impact assessment, routing, duplicate detection)
- Automated communication drafting with appropriate tone and expectations
- Continuous detection gap analysis that improves as the incident evolves
- Full verifiability — every AI decision is traceable, explainable, and replayable
- **Zero trust** on inputs and model outputs (schema validation, human gates on high impact)
- **Structured logging & metrics** so improvement data and future performance dashboards do not require re-instrumentation

This foundation directly attacks the worst cross-cutting problems in traditional incident processes before we layer on more sophisticated investigation or automation capabilities.

### Core docs

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | Project constitution and rules |
| [FIRST_PRINCIPLES.md](docs/FIRST_PRINCIPLES.md) | First principles, zero trust, logging/telemetry constitution |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Ordered Phase 1 build slices |
| [STATE_MACHINE_DESIGN.md](docs/STATE_MACHINE_DESIGN.md) | Lifecycle, data model, human+AI model |
| [PHASE1_SUCCESS_CRITERIA.md](docs/PHASE1_SUCCESS_CRITERIA.md) | What "done" looks like for this phase |
| [PHASE1_EXIT.md](docs/PHASE1_EXIT.md) | Phase 1 sign-off and residual gaps |
| [EVALUATION_RUBRIC.md](docs/EVALUATION_RUBRIC.md) | How we measure cognitive quality |
| [SITE_BRIDGE.md](SITE_BRIDGE.md) | The live incident desk behind vikrantsingh.fyi |
| [docs/proposals/](docs/proposals/) | Designs that are written but not built |

## The Problem We Are Solving

Traditional incident management (even when "ITIL aligned") consistently fails at:

- **Alert fatigue and poor triage** — Important incidents buried, wrong priority, teams overwhelmed
- **Lost context on escalation** — "I thought you knew that" is the most expensive phrase in operations
- **Late or missing communication** — Users feel ignored; status pages are stale
- **Zero systematic learning** — Postmortems are rare, detection gaps are ignored, knowledge evaporates
- **Cognitive load and burnout** — On-call engineers spend most of their time on coordination and reconstruction instead of problem-solving

Our system is designed to make these failure modes structurally difficult.

## Architecture & Principles

- **LLM**: Exclusively Grok via the xAI OpenAI-compatible endpoint
- **Core**: Monolithic Python + simple state machine (SQLite first)
- **First principles**: Critical path is SSOT + lifecycle — not process theater
- **Zero trust**: Untrusted inputs and AI proposals; verify with schemas, policies, and human gates
- **Verifiability First**: Every AI action produces auditable traces
- **Ample logging**: Events, AI traces, structured metrics for later dashboards (UI deferred)
- **Human Authority + AI Agency**: AI proposes and executes low-risk work under policy; humans retain final authority on high-impact decisions
- **Evaluation is Sacred**: Progress is measured through structured rubrics on historical + synthetic incidents, not demos
- **Simplicity**: No speculative agent frameworks. The code must remain readable by a senior engineer in minutes

## Roadmap

### Phase 1 — Foundation (complete, residual gaps)
Verifiable state machine + SSOT + ingest + gated Grok triage + draft comms + detection gaps + CLI + eval harness.

**Build order**: [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)  
**Exit review**: [PHASE1_EXIT.md](docs/PHASE1_EXIT.md)  
**Exit criteria**: [PHASE1_SUCCESS_CRITERIA.md](docs/PHASE1_SUCCESS_CRITERIA.md)

### Next (before Phase 2)

1. Live eval: `python eval_harness.py --live` and keep the summary.
2. Calibrate Low/Medium auto-apply (`0.8` today) from that batch, or leave it and say why. This applies to the engine run on its own; the live desk behind vikrantsingh.fyi runs with `TRIAGE_AUTO_APPLY=off`, so no AI priority applies there without `/approve` ([SITE_BRIDGE.md](SITE_BRIDGE.md)).
3. Add a few historical or real incidents to `fixtures/eval/` (the live desk now produces real ones).
4. Human rubric pass on tone / “would I want this at 3 a.m.”

The shipped loop (propose → gate → log → eval) is the control system. Do not build a reliability/determinism product. After the live eval, optional refinements only: do not re-ask Grok the same question; attach obvious duplicates. Plan: [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

Phase 2 stays closed until that live batch (or an explicit written waiver in `docs/PHASE1_EXIT.md`).

Parked (not building): AI scoring technicians; handoff ping ([proposal](docs/proposals/HANDOFF_PING.md)); bridge stand-down ([proposal](docs/proposals/BRIDGE_STANDOWN.md)); a gate-moving thermostat (rejected; see `docs/FIRST_PRINCIPLES.md`).

### Phase 2 — Verified Investigation
Parallel hypothesis generation with explicit evidence checking and uncertainty handling. Major MTTR reduction on complex incidents.

### Phase 3 — Safe Mitigation & Automation
Auditable suggested fixes and runbook execution with tightening approval gates.

### Phase 4 — Systemic Learning
Automatic problem record creation, knowledge base improvement, predictive signals, and closed-loop improvement **using the logs and evals collected since Phase 1**.

The project follows strict phasing. We only add the next layer after the current foundation is reliable and demonstrably valuable.

## Evaluation Approach

We do not declare success based on anecdotes.

Every meaningful capability is scored using a structured rubric across a growing set of evaluation incidents. Key dimensions include:

- Triage & impact assessment quality
- Communication clarity and usefulness
- Detection gap identification (our signature early capability)
- Overall incident record utility (the "would I want this on a real outage?" score)
- Reasoning transparency and verifiability
- (Operational) override rates and latency metrics from structured logs

Full details: [EVALUATION_RUBRIC.md](docs/EVALUATION_RUBRIC.md)

## Current Status

- Phase 1 slices 0–12 + handoff failsafe complete. Signed off **with residual gaps** — [PHASE1_EXIT.md](docs/PHASE1_EXIT.md)
- Operator path: `ingest` → `propose` → `show` → `approve`. Typed `--confirm` on human transitions. `assign` / `release` / `route` are events.
- Scripted eval (n=10, 2026-08-14): overall 4.5, logging pass, ≥5 high/medium gaps. Live Grok quality **not** certified
- Tests: 124 passed, 1 skipped (live xAI unless key set)
- Company profile is data: edit `company.toml`. Default is Northstar, a public website
- **Usefulness:** a working incident record for one operator (folder + fail-closed gates). Not a production IMOS. Live Grok quality not yet certified.
- **Live:** handles real alerts from [vikrantsingh.fyi](https://vikrantsingh.fyi/reliability/) through GitHub Actions and Issues ([SITE_BRIDGE.md](SITE_BRIDGE.md)).
- **Next:** live eval, then calibrate `0.8`. Not Phase 2. Not a reliability engine.

## Demo

- [Walkthrough (~14 min)](https://youtu.be/j048FYXrRqs): alert in → persist → proposal → human gate → traces.
- [Model down, ticket survives (~3 min)](https://youtu.be/z1tyxIPBWpM).
- Live: the [Incident desk](https://vikrantsingh.fyi/reliability/#incident-desk) on vikrantsingh.fyi.

## Tech Stack (Phase 1)

- Python + Pydantic (strict structured outputs)
- SQLite for state and event log (`store.py`; event log is authoritative)
- Direct Grok calls via xAI HTTP API with `httpx` (`grok.py`)
- Flat, inspectable project structure
- Per-incident folders: `incident.json`, `raw_inputs/`, `ai_traces/`

## Getting Started

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Environment variables (do not commit secrets):

- `XAI_API_KEY` — xAI API key
- `XAI_BASE_URL` — default `https://api.x.ai/v1`
- `XAI_MODEL` — Grok model id

Smoke:

```powershell
python -c "from pydantic import BaseModel; from models import Incident; from transitions import can_transition; from store import Store"
python -m pytest tests/ -q
python app.py
python first_run.py
python cli.py show
python eval_harness.py
```

Operator CLI (`python cli.py`): `ingest` · `propose` · `show` · `approve` · `reject` · `override` · `note` · `transition` · `assign` · `release` · `route` · `export`. Human `transition` requires `--confirm <STATE>`. `release` requires `--confirm RELEASE`. `route` requires `--confirm <group>` and writes `support_group_changed`. `propose` never sends.

To configure another company, edit `company.toml` (or set `INCIDENT_COMPANY_FILE` to your copy) and align `mock_cmdb.json` `owner_team` values with `[[teams]]`. No code change is required to add a team or an intake source.

## Contributing / Philosophy

This project is built with deliberate discipline:

- We ship narrow, high-quality slices per the implementation plan
- Evaluation and dogfooding come before expansion
- Every change must be justifiable against `AGENTS.md` and `docs/FIRST_PRINCIPLES.md`

The most important artifacts are the design documents linked above, the evaluation scores, and the live incident record on the `incident-data` branch.

---

**The goal is not to have agents.**  
**The goal is to make high-quality incident management the default outcome — even at 3 a.m., even when everyone is tired, even on the 47th incident of the quarter.**

We are building the system we wish existed at every company that runs production software.
