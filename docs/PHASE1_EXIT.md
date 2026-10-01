# Phase 1 exit review — 2026-08-14

**Verdict:** Foundation **signed off with residual gaps**. Scripted eval floors pass. Live cognitive quality is **not** certified. Phase 2 investigation stays closed until a live Grok batch or an explicit waiver.

## What was checked

| Check | Result |
|-------|--------|
| `pytest tests/` | 99 passed, 1 skipped (live xAI unless key set) |
| `python eval_harness.py` (scripted, n=10) | overall 4.5; cob 100%; 8 high/medium gaps; logging pass all |
| Phase 1 numeric floors (scripted) | All true |
| 100% AI calls on eval set have traces | Yes — 4 traces per fixture (triage, ack, status, gaps) |
| Metrics extractable without rerun | `runtime/metrics.jsonl` + `event_type=metric` (latency, dwell, confidence, gaps, overrides) |
| Dogfood | `inc-98a409ce6066`: live triage only (empty comms/gaps). **`inc-9cc5373ccc6c` (2026-08-14T23:15Z):** live `propose` — Critical `conf=0.93`, two drafts `sent=false`, 4 gaps, duplicate_of `inc-98a409ce6066`, human approved. Did not auto-merge. |
| CLI lifecycle | DETECTED → CLOSED with human on resolve/close (`tests/test_cli.py`) |
| Readability | Flat Python modules: `models`, `transitions`, `store`, `ingest`, `grok`, `triage`, `comms`, `gaps`, `cli`, `eval_harness`. No agent framework |

Scripted averages: triage 5.0 · comms 4.0 · gaps 4.0 · logging 5.0 · utility 4.5.

Those scores mean **the mocks match ground truth and the wiring works**. They do not mean live Grok is production-ready.

## Mandatory criteria (honest)

1. **SSOT / 6 states / 2 sources** — Pass (alert + manual; event log rebuilds).
2. **Triage** — Wiring pass. Quality pass **only** on scripted fixtures. Live: two Critical dogfoods; not 8–10 live scores.
3. **Comms drafts** — Wiring pass. One live pair on `inc-9cc5373ccc6c` (typo `donot`; internal subject named the duplicate id). Not human-rubric-scored on a batch.
4. **Detection gaps** — Wiring pass. ≥5 HM on scripted set. Live: 4 proposed on `inc-9cc5373ccc6c` (including “did not auto-attach duplicate”). Not batch-scored.
5. **Traces** — Pass on scripted eval and live propose on `inc-9cc5373ccc6c`.
6. **Human gates** — Pass (Critical fail-closed; AI cannot approve).
7. **Structured metrics** — Pass (parse JSONL / metric events).
8. **Engineering quality** — Pass for Phase 1 scope (flat, Grok-only, no swarm).

## Residual gaps (block a clean Phase 1 “done” sticker)

- No mix of **historical** incidents; all 10 eval cases are synthetic.
- No **`--live`** harness run signed off in this review.
- Human rubric (tone, “would I want this at 3 a.m.”) is not multi-rater.
- Auto-apply cutoff 0.8 is still provisional — **calibrate from `--live`**, do not replace it with a moving reliability score.
- CLI stitch for triage/comms/gaps — **closed in Slice 12** (`cli.py propose`; `show` prints bodies).
- `app.py` is still only the CMDB smoke test.

## Slice 12 — operator stitch (done 2026-08-14)

`python cli.py propose --id <id>` runs existing `run_triage` + `draft_ack_and_status` + `analyze_gaps`. Drafts stay `sent=false`. `show` prints ack/status bodies and gap text. Next residual work is live eval, not Phase 2.

## Parked (side note)

Do **not** build AI scoring of technician comments as official record on the live thread. Accountability is the event log + typed confirm + assign/release/route. If revisited: post-incident coaching **proposal** with a human gate — not a model verdict in the scene.

Do **not** build a determinism / cost thermostat. The 2026-08-14 loop (propose → gate → log → eval) is the sounder system. After `--live`: calibrate `0.8`; optional physics (idempotent `propose`, duplicate attach). Never graduate Critical / CLOSE / bounce / typed confirm.

## Phase 2

**Not started.** Verified parallel investigation stays out of scope until live eval on ≥10 incidents or a written waiver in this file.

## Commands to reproduce

```text
python -m pytest tests/ -q
python eval_harness.py
python eval_harness.py --live
python cli.py show
```

---

## Addendum — 2026-08-15

Does **not** change the 2026-08-14 verdict. Residual gaps and the Phase 2 lock still stand.

| Check | Result |
|-------|--------|
| `pytest tests/` | **104 passed, 1 skipped** at the time (live xAI unless key set); the delta from 99 + 1 is Slice 12 + handoff tests. |
| Handoff failsafe | Shipped: human `transition` requires `--confirm` equal to the target state; `assign` / `release` / `route` are events; holder must `release` (type `RELEASE`) or `--steal` with reason. |
| AI technician scoring | **Parked.** Not built. |
| Reliability product | **Rejected.** The shipped loop stays. See `IMPLEMENTATION_PLAN.md`, After Phase 1. |
| Usefulness | A working incident record and circuit breaker for one operator. Not staff. Live Grok quality not yet certified. Next proof: real incidents and `--live` eval. |
