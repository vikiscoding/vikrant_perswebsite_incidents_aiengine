# Site bridge: the live incident desk behind vikrantsingh.fyi

This repo is a fresh start of the Incident-AI engine (imported from `itsm-incident-mgmt-agent@895b805`, code only, no incident data). Here it handles **real alerts from vikrantsingh.fyi**.

## Flow

```
site heartbeat fails twice (Cloudflare Worker)
  → repository_dispatch `site_alert`  →  .github/workflows/site-alert.yml
       ingest as service:vikrantsingh.fyi-heartbeat  →  the agent's own propose (Grok triage, drafts never sent, gaps)
       →  GitHub Issue "[inc-…] …" (label `incident`)  →  feed.json  →  commit to `incident-data`
owner comments /ack, /note, /resolve, /close … on that issue
  → .github/workflows/incident-command.yml  →  the agent's own CLI as human:vikiscoding  →  reply  →  commit
site heartbeat healthy again
  → repository_dispatch `site_recovered`  →  evidence comment; resolving stays a human decision
the site reads feed.json (public raw URL) into its "Incident desk" on /reliability/
```

## Design rules

- **One short run per lifecycle step.** No long-running process. The incident lives in the store, not in a job; that is the agent's "the folder is the ticket" rule.
- **The store is the `incident-data` branch** (`incidents.db`, `incidents/<id>/`, `issues.json`, `site_state.json`, `feed.json`). Every run checks it out, applies one step and commits. Runs share one concurrency group, so they never overlap. Git history is the backup and the audit trail.
- **`service:<name>` actors may only ingest** (`models.SERVICE_EVENT_TYPES`). They can never transition, approve or hand off; those keep `validate_actor`. Tested in `tests/test_service_actor.py`.
- **Only the owner's comments run commands**, enforced in the workflow `if:` and again in `site_bridge.py`. The comment text reaches Python only through an env var, never a shell line.
- **The incident record beats the GitHub thread.** Closing an incident issue with the button reopens it (`incident-guard.yml`) unless the record is CLOSED. Refused commands say which step is valid next, and `/ack` takes only the steps still needed.
- **The command word is the typed confirmation.** `/resolve` passes `--confirm RESOLVED` to the CLI; holder checks and the lifecycle's `requires_human` rules apply unchanged.
- **The model never sets priority on the live desk.** `site-alert.yml` runs with `TRIAGE_AUTO_APPLY=off`, so every AI priority, even a confident Low, waits for the owner's `/approve`. Paging never depends on the model: it comes from the site's outside probe on its SLO. (The eval harness and tests keep the default policy.)
- **The model is optional.** Without `XAI_API_KEY`, or on a Grok failure, the incident is still created and a human triages it.
- **Visitors cannot create incidents.** Only the site Worker (with a dispatch token) and the owner (manual run) can.

## Commands (owner only)

`/approve` · `/reject <reason>` · `/priority <Critical|High|Medium|Low> <reason>` · `/ack` (ACKNOWLEDGED → ACTIVE) · `/note <text>` · `/resolve <reason>` · `/close [reason]` · `/reopen <reason>`

## Secrets

| Where | Name | Purpose |
| --- | --- | --- |
| This repo | `XAI_API_KEY` | Grok triage and drafts (optional; model-down path without it) |
| Workflow env | `TRIAGE_AUTO_APPLY=off` | Live desk: no AI priority applies without `/approve` |
| Site Worker (Cloudflare) | `INCIDENTS_DISPATCH_TOKEN` | Fine-grained token, this repo only, **Contents: read and write** (needed for `repository_dispatch`) |

## Try it without the site

Actions → **site-alert** → Run workflow → `site_alert`. Then comment `/ack` on the new issue.
