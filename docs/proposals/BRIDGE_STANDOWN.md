# Proposal: bridge stand-down

**Status:** Proposal, not built. Not a slice. Not Phase 2. Not a reliability product.  
**When:** After live eval, and only after `HANDOFF_PING.md` bounce exists (or with it). The ping is for the group **in the spotlight**. This is for everyone **still on the call**.  
**Why:** Major-incident bridges waste hours because leaving feels like abandonment. Teams stay after they are neither on the causal path nor needed for recovery. There is no formal “you may go.”

One idea: *silence is not leave. The IM issues a code. You type it. Then you are off the roster.*

This is the same DNA as typed `RELEASE` / `--confirm`. It is **not** “the model statistically decided Application is innocent.”

---

## Two sets (today we only have one)

| Set | Meaning | Today |
|-----|---------|--------|
| **Spotlight** | Current `support_group` + optional `assigned_to` | Exists (`route` / `assign`) |
| **Involved** | Resolver groups still on the bridge, including those no longer in the spotlight | **Missing.** Bounce today forgets you were ever here. |

`company.toml` owning teams are the only legal names.

**Join involved (append-only add):**
- Ingest routing hint
- Any `support_group_changed` `to`
- Explicit `involve --group` by a human (IM or spotlight holder)

**Leave involved:** only stand-down below. Bounce does **not** remove the previous group. That is the point.

RESOLVED / CLOSED stands everyone down in one event (`bridge_cleared`) with the closer as actor. No per-group codes at the end of the incident.

---

## Who may issue the code

**Incident manager** is one human on the record, not a role engine.

```text
python cli.py im --id INC --actor human:vikrant --to human:vikrant --confirm IM
```

Event: `incident_manager_changed`. If `incident_manager` is unset, **nobody** can stand a group down. Fail closed.

Only that IM can mint a stand-down code. Grok cannot. A resolver cannot mint their own exit.

---

## Stand-down (two steps)

**1. IM mints** (after they believe both are true):

```text
python cli.py standdown-issue --id INC --actor human:vikrant --group Edge --confirm Edge
```

Required on the IM (or they refuse to mint):
- Not suspected as origin of the fault (text, not a checkbox-only)
- Not needed for recovery (text, not a checkbox-only)

Grok may have proposed those two sentences (`standdown_proposed`). The IM may edit. The IM still types the group name.

The code is a short one-time string, stored hashed or as the event id suffix — **not** a game PIN. Shown once to the IM to read onto the bridge. Expires when used or when the IM revokes.

**2. Someone in that group accepts:**

```text
python cli.py standdown-accept --id INC --actor human:priya --group Edge --code THECODE --confirm Edge
```

Actor must be human. Group must match. Code must match the open mint. Then they are off `involved`.

Event payload:

```json
{
  "group": "Edge",
  "issued_by": "human:vikrant",
  "accepted_by": "human:priya",
  "not_on_causal_path": "CDN 200s; origin 5xx. Edge path clean.",
  "not_needed_for_recovery": "No config change on our side; rollback is Application.",
  "code_id": "sd-…"
}
```

**Cannot stand down the current spotlight group.** Bounce or resolve first. Otherwise “Application left while they still own the ticket.”

**Recall:** IM can `involve` them again. New event. No silent undo.

---

## What the card shows (same family as `HANDOFF_PING.md`)

Spotlight card: the owning group (already specified).

Involved-but-not-spotlight: a quieter line, not a second product.

```
still on bridge   Edge   Platform
spotlight         Application   holder human:vikrant
leave             IM code only
```

No pulse contest. The incentive is: do the check, write the two sentences, get the code, go back to work. Human hours drop because **permission to leave is explicit**, not because the system guessed.

---

## Grok’s job (propose only)

May draft `standdown_proposed` for a non-spotlight involved group: the two sentences + evidence. Same as triage. IM may ignore.

Must not: auto-mint, auto-accept, drop a group because confidence was high, or clear the spotlight.

---

## Explicit non-goals

- Auto-leave when routed away
- “This team is usually innocent” from history (that is the thermostat — rejected)
- Slack/page send of the code (send path)
- Points, SLA theater, or a second dashboard
- A role/plugin framework for “who is IM”
- Standing down without the two texts

---

**Build order if picked up:** involved set + IM field + issue/accept events on the CLI first; card later next to the ping.
