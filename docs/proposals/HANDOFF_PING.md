# Proposal: handoff ping

**Status:** Proposal, not built. Not a slice. Not Phase 2. Not a dashboard.  
**When:** After live eval has a home. The ledger already exists (`assign` / `release` / `route`). This is the always-on face of that ledger on the bridge. Sister spec (also parked): `BRIDGE_STANDOWN.md` — groups still involved but not in the spotlight; they leave with an IM code, not by bouncing.  
**Why:** Tickets bounce between resolver groups with “I thought you had it.” Time-in-queue is invisible. The bounce reason is one free-text blob (`route --reason`). Context dies in the call.

One idea: *while your group owns it, the ticket stares at you. You cannot throw it without saying what you did and why you are done.*

---

## What it is

A single popped-out / always-visible card for the **owning support group** while the incident is not `RESOLVED` or `CLOSED`. It pings. It does not become a console, a chat, or a status page.

```
┌─────────────────────────────────────────────────────────┐
│  inc-9cc5…     CRITICAL     ACTIVE     Application      │
│  website 5xx — checkout errors                          │
│                                                         │
│  incident age      00:47:12                             │
│  in this queue     00:12:04                             │
│  holder            human:vikrant                        │
│                                                         │
│  landed here from  Edge                                 │
│  put here by       human:priya     14:02  (ledger)      │
│                                                         │
│  [ bounce to another queue ]                            │
└─────────────────────────────────────────────────────────┘
```

Pulse while this group owns it. Faster pulse is allowed later as a dwell hint — not an SLA product.

---

## Timers (derived, never typed)

| Clock | From | Until |
|-------|------|--------|
| Incident age | `created_at` | now |
| Time in this queue | last `support_group_changed` timestamp, else `created_at` | now |
| Time on this holder (optional, same card) | last `assignment_changed` | now, or hidden if unheld |

These are facts. The card does not let anyone edit them.

---

## Bounce is the only mutation

The card cannot approve triage, send comms, resolve, or close. Those stay on `cli.py`.

To change `support_group`, the form is required. Today's `route --reason` is **not enough**.

| Field | Who fills it | Rule |
|-------|----------------|------|
| Who put it in our queue | **Nobody types this.** Prefill from last `support_group_changed.actor` (or ingest actor if never routed). Human **confirms** the prefill. | Cannot invent a different person. Ledger wins. |
| What we did at this step | Free text | Required. Min length. Not “looked” / “n/a”. Becomes `work_done`. |
| Why no work left at our level | Free text, **separate** from work done | Required. Not “escalating” / “not us” alone. Becomes `why_not_us`. |
| Who owns it next | Select from `company.toml` owning teams, excluding the current group | Required. Typed confirm = the group name. Becomes `to`. |
| Suggested next person | Optional | Hint only. Does **not** `assign`. Next group still has to take the hold. |

Actor is the human hitting bounce (`human:<id>`). AI cannot bounce.

### Event (same type, richer payload)

`support_group_changed`:

```json
{
  "from": "Application",
  "to": "Data",
  "received_from": "human:priya",
  "received_from_confirmed": true,
  "work_done": "checked app pods; 5xx correlate with checkout-api waiting on postgres",
  "why_not_us": "connection pool exhausted; we do not own the database",
  "suggested_holder": null
}
```

Keep `reason` as a copy of `why_not_us` so old readers do not break. Fail closed if `work_done` or `why_not_us` is missing when this slice exists.

CLI shape when built (UI is a form over this):

```text
python cli.py bounce --id INC --actor human:vikrant --to Data --did "..." --why-not-us "..." --confirm Data
```

No `--received-from` flag. The store writes it from the last route/ingest.

---

## Surface (when we build)

1. **First:** `cli.py bounce` with the four required fields. Tests: missing `work_done` dies; invented `received_from` dies; AI actor dies; confirm ≠ group dies.
2. **Then:** one local HTML card, no framework, no login. `python cli.py ping --id INC` or `--group Application` opens/refreshes it from `incidents/{id}/incident.json`. Poll the folder. If Grok is down the card still ticks.
3. **Not in this slice:** Slack/Teams/page send (that is a send path). Multi-incident board. AI picking the next group (triage already *proposes* routing; a human still selects). Live scoring of the bounce text.

The card must show the same ids, actors, and timestamps as `cli.py show`. If the UI and the folder disagree, the folder wins and the card is wrong.

---

## Explicit non-goals

- Dashboard, auth, ServiceNow, toast platforms
- Model-as-judge of the bounce paragraph (see Parked: technician scoring)
- Auto-assigning the next human
- Letting silence bounce the ticket
- Skipping `work_done` / `why_not_us` / typed confirm because override rate or confidence looked good (blast radius is not graduated)

---

**Status:** parked until live eval exists.
