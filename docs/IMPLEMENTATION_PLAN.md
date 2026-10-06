# Implementation Plan — Phase 1 (Verifiable Incident Brain)

**Status:** Phase 1 slices 0–12 + handoff failsafe complete. The shipped loop **is** the control system: one operator + folder + fail-closed gates; not a production IMOS; live Grok quality not yet certified. Next: `--live` eval. Not Phase 2. No reliability product. See `PHASE1_EXIT.md`.  
**Date:** 2026-08-15  
**Governs:** Phase 1 code (closed except residual-gap work). Phase 2 is not opened by this file.  
**Must obey:** `AGENTS.md` · `FIRST_PRINCIPLES.md` · `STATE_MACHINE_DESIGN.md` · `PHASE1_SUCCESS_CRITERIA.md` · `EVALUATION_RUBRIC.md`

This is a **build plan**, not a product “flywheel.”  
First principles, zero trust, and telemetry-ready logging are **constraints on every slice**, not a separate subsystem to invent.

---

## Guiding constraints (every slice)

1. **First principles** — implement critical path only; no agent frameworks, no speculative UI.  
2. **Zero trust** — validate inputs; schema-validate AI; fail closed on high-impact actions; explicit actors.  
3. **Ample logging** — events + AI traces + structured metrics fields from the first AI call; dashboards later consume these logs only.  
4. **Eval-gated promotion** — cognitive features ship only when rubric/harness evidence exists.  
5. **Stack** — Python, Pydantic, SQLite, direct Grok (xAI OpenAI-compatible). Flat layout. No LangChain/LangGraph/multi-model.  
6. **This loop is enough** — Grok proposes; code owns the gate; humans own Critical / CLOSE / bounce / typed confirm; eval scores from outside. Do not add a second loop that watches scores and moves the gate (`FIRST_PRINCIPLES.md` §4). Token savings are physics (do not ask twice; code already knows), not a reliability product.

---

## Current baseline

| Item | State |
|------|--------|
| Design docs | Present (this plan updates them) |
| `app.py` | CMDB JSON validator only (not the incident brain) |
| Dependencies | Slim: `pydantic` + `pytest` + `httpx` (xAI only; no OpenAI/Groq SDK) |
| `models.py` / `transitions.py` | Slice 1 done — models + `can_transition` |
| `store.py` | Slice 2 done — SQLite event log + `incidents/{id}/` artifact tree |
| Org / CMDB | `company.toml` is the configurator file (teams, lifecycle, intake). Default profile: Northstar public website |
| `cmdb.py` / `ingest.py` | Slice 4 done — alert + manual ingest, CMDB join, priority ignored |
| Metrics | Slice 3 done — `event_type=metric` + `runtime/metrics.jsonl`. No dashboard |
| `grok.py` | Slice 5 done — httpx client, structured parse, always-on `ai_traces/` |
| `triage.py` | Slice 6 done — Grok proposes `TriageResult`; High/Critical and low confidence gated |
| `comms.py` | Slice 7 done — ack + status drafts only; never sent |
| `gaps.py` | Slice 8 done — living detection gaps, append-only, human confirm/reject |
| `cli.py` | Slice 9 done — ingest/show/approve/reject/override/note/transition/export |
| `eval_harness.py` | Slice 10 done — 10 fixtures, ground-truth scores, `evaluations/` |
| Exit review | Slice 11 done — see `PHASE1_EXIT.md`. Scripted floors pass; live quality not certified |
| Operator stitch | Slice 12 done — `cli.py propose` + `show` prints draft bodies and gaps |
| Handoff failsafe | Done 2026-08-15 — typed `--confirm` on human transition; `assign` / `release` / `route` events |
| Auto-apply | Shipped: Low/Medium + `confidence ≥ 0.8`. Cutoff **provisional** until live eval. Saves human wait, not API calls. High/Critical always gated. **Off on the live desk** (`TRIAGE_AUTO_APPLY=off`, since 1 Oct 2026): there every AI priority waits for `/approve`. |
| Cost / determinism policy | **Rejected as a product.** Sounder version is what already shipped. After `--live` only: calibrate `0.8`; then optional physics cuts (idempotent `propose`, duplicate attach). No thermostat. |
| Production incident path | Phase 1 foundation signed off with residual gaps. Phase 2 not started |

---

## Phase 1 slices (ordered)

Each slice has: **outcome**, **deterministic vs AI**, **zero-trust rules**, **logs/metrics**, **done check**.

### Slice 0 — Project hygiene & dependency truth

**Outcome:** Repo dependencies and layout match `AGENTS.md`.

- Inventory and trim runtime deps to: Python stdlib + `pydantic` + HTTP client for xAI + (optional) pytest.  
- Remove / stop relying on LangChain, LangGraph, Streamlit, non-xAI LLM SDKs for new code.  
- Confirm `.venv` works; document `XAI_API_KEY` (or equivalent) env var without committing secrets.  
- Keep `mock_cmdb.json` + existing CMDB validation as a utility module if useful.

**Logs:** N/A (repo hygiene).  
**Done when:** `requirements.txt` matches intended stack; `python -c` import smoke test passes.

---

### Slice 1 — Domain models + illegal-transition guard (deterministic)

**Outcome:** Pydantic models and state transition rules as code, matching `STATE_MACHINE_DESIGN.md`.

- `IncidentState`, `IncidentEvent`, `Incident`, `TriageResult`, `CommunicationDraft`, `DetectionGap`.  
- Pure function: `can_transition(from, to, policy_context) -> bool` + required human gate flags.  
- Unit tests: legal paths, illegal paths, reopen/escalate require human.

**Zero trust:** No state change API that bypasses the guard.  
**Logs:** None yet (in-memory / pure).  
**Done when:** Tests cover the transition table; models reject bad types.

---

### Slice 2 — Persistence + per-incident artifact tree (deterministic)

**Outcome:** SSOT on disk + SQLite.

- SQLite: `incidents` snapshot + append-only `incident_events`.  
- Filesystem:  
  `incidents/{id}/incident.json`  
  `incidents/{id}/raw_inputs/`  
  `incidents/{id}/ai_traces/`  
- API (functions or thin CLI): create incident from raw payload; append event; materialize snapshot from events.

**Zero trust:** Raw inputs immutable once written; events append-only; actor required on every event.  
**Logs / metrics fields on events:** `event_type`, timestamps, actor, from/to state.  
**Done when:** Create → transition → reload process reconstructs full timeline without LLM.

---

### Slice 3 — Structured metrics emission (deterministic, dashboard-ready)

**Outcome:** Emit the Phase 1 metric set defined in `FIRST_PRINCIPLES.md` §3.2 as structured records.

- Prefer: `event_type="metric"` rows and/or `runtime/metrics.jsonl`.  
- Helpers: `emit_metric(name, value, incident_id, labels)`.  
- Wire timers around create, triage, ack draft (stubs OK until Slice 5–6).

**Zero trust:** Metrics never replace domain events; no PII/secrets in metric labels.  
**Done when:** Running a mock lifecycle writes parseable metric records for at least time-in-state and stub latencies.

---

### Slice 4 — Ingestion from ≥2 sources (deterministic + validation)

**Outcome:** Ingest mock alert JSON + manual report into `DETECTED` → ready for triage.

- Source-tagged adapters; schema validation; store raw under `raw_inputs/`.  
- Optional CMDB snapshot attach from `mock_cmdb.json` (deterministic join by service name/id).

**Zero trust:** Untrusted input → validated model or reject; never trust caller-supplied priority as final without triage path.  
**Logs:** Ingestion event + raw path references.  
**Done when:** Two source types produce comparable `Incident` records and pass tests.

---

### Slice 5 — Grok client + AI trace contract (zero trust on model I/O)

**Outcome:** Single thin Grok client; every call writes a complete trace.

- OpenAI-compatible xAI endpoint only.  
- `complete_structured(prompt, schema) -> parsed | error`.  
- On every call write `ai_traces/{trace_id}.json`: model, timestamps, latency_ms, prompt, raw response, parsed output or error, incident_id, purpose.  
- Fail soft: return error object; caller degrades without corrupting state.

**Zero trust:** Parse failures do not become silent defaults; confidence required on success paths that auto-apply.  
**Metrics:** `ai_call_latency_ms`, `ai_call_error`.  
**Done when:** Integration test with mocked HTTP (and optional live smoke) proves trace files always appear.

---

### Slice 6 — Intelligent triage (AI propose + gate)

**Outcome:** `TriageResult` proposed, stored, scored path ready.

- Prompt + structured output → validate → `ai_triage` on incident + events.  
- Policy: High/Critical priority proposals set `requires_approval=True`.  
- Human override command updates fields via new events (not silent mutation).

**Zero trust:** AI priority is proposal until approved/policy auto-accept (Low/Medium + high confidence only, if enabled).  
**Logs/metrics:** `time_to_triage_ms`, `ai_confidence`, `human_override`, `duplicate_detected`.  
**Done when:** ≥1 synthetic fixture runs end-to-end to triaged state with full traces; rubric can be applied manually.

---

### Slice 7 — Communication drafts (AI propose)

**Outcome:** Initial ack + ≥1 status update as `CommunicationDraft`s.

- Draft-first; Phase 1 does not require real email/Slack send.  
- Audience-aware prompts (internal vs customers vs leadership).  
- Event: `communication_drafted` with artifact reference.

**Zero trust:** No external send without explicit future policy; drafts are proposals.  
**Metrics:** `time_to_first_ack_draft_ms`.  
**Done when:** Eval fixtures produce drafts scorable on communication dimension ≥ target path in success criteria.

---

### Slice 8 — Living detection gap analysis (AI propose)

**Outcome:** `DetectionGap` list updated during triage/active; persisted on incident.

- Prompt with timeline + context; merge new gaps without deleting human-confirmed history (append + status field if needed).  
- Link suggested monitoring/runbook changes.

**Zero trust:** Gaps are hypotheses with evidence field required; no gap without evidence string.  
**Metrics:** `detection_gap_count` by severity.  
**Done when:** On first eval batch, total high/medium gaps meet `PHASE1_SUCCESS_CRITERIA` threshold path.

---

### Slice 9 — Human-in-the-loop CLI surface

**Outcome:** Minimal CLI/script commands for real operation.

Commands (illustrative names):

- `ingest` · `show` · `approve` · `reject` · `override` · `note` · `transition` · `export`

**Zero trust:** Approve/reject require human actor string; high-impact transitions blocked without approval event.  
**Logs:** All actions as events; `approval_wait_ms` when measurable.  
**Done when:** Full lifecycle demo: DETECTED → … → CLOSED with at least one human approval, inspectable folder.

---

### Slice 10 — Evaluation harness (independent verification)

**Outcome:** Replay fixtures; score or attach scores; store under `evaluations/`.

- Fixture format: raw input + ground truth triage/priority + optional expected gaps.  
- Run system offline-ish (mock Grok or recorded traces for regression; live Grok for quality runs).  
- Output: per-incident dimension scores + notes per `EVALUATION_RUBRIC.md`.  
- Gate: document command to run harness before claiming slice improvements.

**Zero trust:** Harness scores are external to the model; model cannot self-certify.  
**Logs:** Full scored bundles; link to traces used.  
**Done when:** 8–10 fixtures runnable; average overall utility and dimension floors tracked against Phase 1 exit criteria.

---

### Slice 11 — Phase 1 hardening & exit review

**Outcome:** Meet `PHASE1_SUCCESS_CRITERIA.md` or explicitly list residual gaps.

- Dogfood or realistic replay.  
- Readability check (senior engineer <5 minutes).  
- Confirm 100% AI decisions on eval set have traces.  
- Confirm metrics.jsonl / metric events sufficient for a *future* dashboard (no UI required).  
- Update README status and `PHASE1_EXIT.md`.

**Done when:** Exit criteria checklist signed off in `PHASE1_EXIT.md`.

### Slice 12 — Operator stitch (residual gap — **done**)

**Status:** Done. Phase 1 residual work, not Phase 2.

**Why this is next (rationale):**  
`FIRST_PRINCIPLES.md` critical path is `signal → persist → triage → comms draft → gate → log`. Slices 6–8 already implement triage, draft-only comms, and gaps. Slice 9 CLI only wraps ingest/show/approve. `live_triage.py` stops after triage. The eval harness is the only place comms+gaps run, and only on synthetic fixtures. Dogfood `inc-98a409ce6066` has live gated triage and empty `communications` / `detection_gaps`. A human cannot reconstruct the full critical path on one id without leaving the operator surface. That is an incomplete critical path, not a missing product. The 12-minute demo (since recorded) was blocked on this stitch; live `--live` certification and historical fixtures remain required for a Phase 1 “done” sticker but are **not** the next code slice.

**Outcome:** One trusted operator, one incident id, one CLI:

`ingest → propose (triage + ack/status drafts + gap proposals) → human approve/reject → show prints draft bodies and gap text → folder + traces still reconstruct without the CLI`

**Deterministic vs AI:** CLI wiring is deterministic. Grok is only called through existing `run_triage`, `draft_ack_and_status`, `analyze_gaps`. No new model path. No send.

**Zero-trust rules:**

- Mutating commands still require `--actor human:<id>` where a human authorizes; AI actor cannot approve, close, confirm gaps, or send.
- Drafts remain artifacts. No email, Slack, status-page, or HTTP listener.
- Fail closed unchanged: High/Critical and low confidence still need human approve; illegal transitions still die.
- Do not add auth, a web UI, ServiceNow, or investigation/hypothesis code.
- Do not treat this slice as a security-hardening sprint. Known nits (sanitize `incident_id` paths; redact secrets inside stored prompts) wait until a caller other than the local operator exists. Do not weaken actor checks or append-only triggers.

**Logs / metrics:** Reuse existing events and traces. No new dashboard. `show` must print enough that a viewer need not open eval JSON.

**Done when:**

- `cli.py` can run triage, comms drafts, and gap propose on an existing id (one `propose` command or three verbs — prefer the smallest surface).
- `cli.py show <id>` prints ack/status **bodies** and at least gap description + severity + status (not only counts).
- Tests: AI cannot approve; drafts never send; one test incident has comms ≥2 and ≥1 gap after the operator path.
- The demo uses only `cli.py` (plus `eval_harness.py` for the honest scripted score). `live_triage.py` may remain as a thin alias or be deleted if unused.
- No Phase 2 waiver. Live quality still not certified.

**Out of scope for Slice 12:** UI, ServiceNow, `--live` batch sign-off, historical fixtures, ATF, multi-rater rubric, `app.py` as a product, new repos.

---

## Explicit non-goals (Phase 1)

- Multi-agent investigation swarms  
- Autonomous production remediation  
- Full web UI / performance dashboard product  
- Postgres/pgvector, multi-LLM routing  
- Inventing a separate “initiator flywheel” service  
- A determinism / cost / “proof matching” engine that moves gates from override rate, confidence, or eval trends  
- Using Grok to decide whether to call Grok  
- Graduating Critical, CLOSE, bounce fields, or typed confirm because the last N were clean  

---

## Suggested calendar (solo builder, indicative)

| Week focus | Slices |
|------------|--------|
| 1 | 0–3 (hygiene, models, store, metrics) |
| 2 | 4–6 (ingest, Grok client, triage) |
| 3 | 7–9 (comms, gaps, CLI) |
| 4 | 10–11 (eval harness, exit or gap list) |

Adjust for live Grok iteration time; quality runs may dominate Week 3–4.

---

## After Phase 1 (next work)

**Now:** Slice 12 and the handoff failsafe are done. The shipped propose → gate → log → eval loop is the sounder system. Next proof: real incidents through the live desk (`SITE_BRIDGE.md`) and `--live` eval. Not Phase 2. Not a reliability product. Do not claim more than one operator's tool until that evidence exists.

Then, still before any investigation swarm:

1. `python eval_harness.py --live` and keep `evaluations/{date}/summary.json` (~40 structured calls, a sitting, not a heartbeat).
2. From that summary + `human_override` / traces: **calibrate** `AUTO_APPLY_MIN_CONFIDENCE` (today `0.8`) or write why it stays. This saves approvals, not tokens.
3. Add real or historical fixtures under `fixtures/eval/`.
4. Human-score comms / overall utility on that batch.

**After the live eval exists (optional refinements, not a new slice until then):**

| Cut | What | Must not become |
|-----|------|-----------------|
| Idempotent `propose` | No new events/inputs → reuse last traces. Second `propose` today is four wasted calls. | A “trust tier” |
| Duplicate attach | Same open CI + same monitor in the window → attach; no new triage. | Auto-merge of SSOT |
| Shadow route (later) | Log CMDB `routing_hint` vs Grok route. Skip the *triage* call only on Low + boring agreement + same-day revert. | Skip Critical / CLOSE / bounce / confirm |

**Parked:** AI grading technician notes. Handoff ping card (`proposals/HANDOFF_PING.md`). Bridge stand-down (`proposals/BRIDGE_STANDOWN.md`) — involved roster, IM-issued leave code. Determinism thermostat (rejected — see constraint 6).

## Definition of “ready for Phase 2”

Phase 2 (verified investigation) starts only when:

1. Phase 1 mandatory success criteria pass on ≥10 evaluation incidents, **or**  
2. Explicit written waiver of residual gaps with rationale in `PHASE1_EXIT.md`.

Until then, investigation-swarm work is out of scope.

---

## How to use this plan in a coding session

1. Open `AGENTS.md` + `FIRST_PRINCIPLES.md` + this file.  
2. Pick the **lowest unfinished item** in After Phase 1 (demo → live eval → calibrate `0.8`). There is no thermostat slice.  
3. Implement only that outcome, zero-trust rules, and logs.  
4. Run tests / harness for that work.  
5. Update “Current baseline” mentally; log major decisions in `PHASE1_EXIT.md` (or a new doc under `docs/`) when architecture shifts.

**Ship the critical path. Trust nothing by default. Log everything that future-you will need to measure.**
