"""Bridge between vikrantsingh.fyi and the incident engine, run by GitHub Actions (see SITE_BRIDGE.md).

Every lifecycle step is one short run against the store on the `incident-data` branch:
  alert      site heartbeat failed  -> ingest as service:<name>, then the agent's own propose (never sends)
  recovered  site heartbeat healthy -> evidence for the open incident; resolving stays a human decision
  command    owner's /command on the incident's GitHub Issue -> the agent's own CLI (typed confirm, holder checks)
  link       remember which GitHub Issue belongs to which incident
  feed       write feed.json, the public summary the site's dashboard reads

Zero trust: the alert payload and the comment text are untrusted strings, size-capped and validated here.
The workflow only calls `command` for comments by the repo owner on issues labelled `incident`.
"""

import argparse
import contextlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import cli
from cmdb import Cmdb
from grok import GrokClient
from ingest import ingest
from store import Store

SERVICE_ACTOR = "service:vikrantsingh.fyi-heartbeat"
OWNER = "vikiscoding"
HUMAN_ACTOR = f"human:{OWNER}"
OPEN_STATES = {"DETECTED", "TRIAGING", "ACKNOWLEDGED", "ACTIVE"}
FEED_LIMIT = 20

HELP = """Commands (repo owner only, first line of a comment):
  /approve                  accept the AI's proposed triage
  /reject <reason>          reject it (the priority stays human-owned)
  /priority <P> <reason>    set priority: Critical | High | Medium | Low
  /ack                      acknowledge and start work (ACKNOWLEDGED -> ACTIVE)
  /note <text>              add a note to the timeline
  /resolve <reason>         mark resolved (always human)
  /close [reason]           close (always human); closes this issue
  /reopen <reason>          back to ACTIVE
The command word is the typed confirmation; only the owner's account is obeyed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _out(**values: str) -> None:
    """Write step outputs for the workflow (multi-line safe)."""
    path = os.environ.get("GITHUB_OUTPUT")
    for key, value in values.items():
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"{key}<<__EOF__\n{value}\n__EOF__\n")
        else:
            print(f"--- {key} ---\n{value}")


def _clip(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _json_file(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


# ---------------------------------------------------------------- alert / recovered

def parse_alert(raw: str) -> dict:
    if len(raw) > 4096:
        raise ValueError("alert payload too large")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("alert payload must be an object")
    alert = {
        "monitor": _clip(data.get("monitor"), 100),
        "service": _clip(data.get("service"), 100),
        "message": _clip(data.get("message"), 300),
        "fired_at": _clip(data.get("fired_at") or _now(), 40),
    }
    missing = [k for k in ("monitor", "service", "message") if not alert[k]]
    if missing:
        raise ValueError(f"alert payload missing {missing}")
    return alert


def open_incident_for(store: Store, alert: dict):
    """The open incident for the same monitor AND service. Matching on service alone let an open manual test
    swallow a real alert (game day 1, 1 Oct 2026). The reporter is rendered as alert:{monitor} by company.toml."""
    reporter = f"alert:{alert['monitor']}"
    for row in store.summaries():
        incident = store.get_incident(row["id"])
        if (incident.current_state.value in OPEN_STATES and incident.reporter == reporter
                and alert["service"] in incident.affected_services):
            return incident
    return None


def issue_body(incident) -> str:
    t = incident.ai_triage
    lines = [f"**Incident** `{incident.id}` · state **{incident.current_state.value}** · opened {incident.created_at.isoformat(timespec='seconds')}", ""]
    lines.append(f"**Alert:** {incident.title}")
    lines.append(f"**Ingested by:** `{SERVICE_ACTOR}` (machine intake; it can never move or approve this incident)")
    lines.append("")
    if t:
        gate = gate_label(incident)
        lines += [
            "### AI proposal (not applied unless the gate says so)",
            f"- Priority **{t.priority}** · impact {t.impact_score} · confidence {t.confidence:.2f} · gate: **{gate}**",
            f"- Reasoning: {_clip(t.reasoning, 600)}",
            "",
        ]
    else:
        lines += ["### AI proposal", "- None. The model was unavailable or failed; a human triages this one (the ticket survives).", ""]
    for draft in incident.communications[:2]:
        lines += [f"### Draft: {draft.audience} ({draft.channel}). **Not sent**", f"> **{_clip(draft.subject, 160)}**", f"> {_clip(draft.body, 700)}", ""]
    if incident.detection_gaps:
        lines.append("### Detection gaps")
        lines += [f"- {gap.severity}: {_clip(gap.gap_description, 200)}" for gap in incident.detection_gaps[:5]]
        lines.append("")
    lines += ["---", "```", HELP, "```"]
    return "\n".join(lines)


def cmd_alert(store: Store, raw: str) -> int:
    alert = parse_alert(raw)
    existing = open_incident_for(store, alert)
    if existing:
        _out(mode="duplicate", incident_id=existing.id,
             reply=f"Alert fired again at {alert['fired_at']}: {alert['message']}\n\nSame open incident; no new ticket.")
        return 0
    incident = ingest(store, "alert", alert, SERVICE_ACTOR, Cmdb.load())
    grok = GrokClient(store, progress=False)
    try:
        cli.run_propose(store, grok, incident.id)  # triage + drafts + gaps; drafts are never sent
    except Exception as exc:  # the ticket survives a model failure; a human finishes
        print(f"propose failed, continuing without AI: {exc}", file=sys.stderr)
    finally:
        grok.close()
    incident = store.get_incident(incident.id)
    _out(mode="new", incident_id=incident.id, title=f"[{incident.id}] {_clip(incident.title, 120)}", body=issue_body(incident))
    return 0


def cmd_recovered(store: Store, root: Path, raw: str) -> int:
    alert = parse_alert(raw)
    incident = open_incident_for(store, alert)
    if not incident:
        _out(mode="none", incident_id="")
        return 0
    state = _json_file(root / "site_state.json", {})
    state.setdefault(incident.id, {})["recovered_at"] = alert["fired_at"]
    (root / "site_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    _out(mode="recovered", incident_id=incident.id,
         reply=f"Site reports recovery at {alert['fired_at']} ({alert['message']}).\n\n"
               "Resolving is a human decision: reply `/resolve <reason>` once you have checked it.")
    return 0


# ---------------------------------------------------------------- owner commands

def _run_cli(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse errors
            code = int(exc.code or 1)
    return code, buf.getvalue().strip()


NEXT_STEP = {
    "DETECTED": "`/ack` (acknowledge and start work)",
    "TRIAGING": "`/ack` (acknowledge and start work)",
    "ACKNOWLEDGED": "`/ack` (start work: ACTIVE)",
    "ACTIVE": "`/resolve <reason>`",
    "RESOLVED": "`/close` (or `/reopen <reason>`)",
    "CLOSED": "nothing; it is closed (or `/reopen <reason>`)",
}


def plan_command(text: str, incident_id: str, issue: str, state: str = "TRIAGING") -> list[list[str]] | str:
    """Map an owner's comment to agent CLI calls, or return a help/error message."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    if not first.startswith("/"):
        return "Not a command."
    verb, _, rest = first[1:].partition(" ")
    verb, rest = verb.lower(), _clip(rest, 500)
    base = ["--id", incident_id, "--actor", HUMAN_ACTOR]
    via = f"via GitHub issue #{issue}"

    def move(state: str, reason: str) -> list[str]:
        return ["transition", *base, "--to", state, "--confirm", state, "--reason", f"{reason} ({via})"]

    if verb == "approve":
        return [["approve", *base]]
    if verb == "reject":
        return [["reject", *base, "--reason", rest]] if rest else "`/reject` needs a reason."
    if verb == "priority":
        value, _, reason = rest.partition(" ")
        if value.capitalize() not in {"Critical", "High", "Medium", "Low"} or not reason:
            return "Use `/priority <Critical|High|Medium|Low> <reason>`."
        return [["override", *base, "--field", "priority", "--value", value.capitalize(), "--reason", f"{reason} ({via})"]]
    if verb == "ack":  # only the steps still needed from the current state
        steps = {"DETECTED": ["TRIAGING", "ACKNOWLEDGED", "ACTIVE"], "TRIAGING": ["ACKNOWLEDGED", "ACTIVE"], "ACKNOWLEDGED": ["ACTIVE"]}
        path = steps.get(state)
        if not path:
            return f"Nothing to acknowledge: the incident is {state}. Next: {NEXT_STEP.get(state, '`/help`')}."
        reasons = {"TRIAGING": "human takes triage", "ACKNOWLEDGED": "acknowledged", "ACTIVE": "work started"}
        return [move(s, reasons[s]) for s in path]
    if verb == "note":
        return [["note", *base, "--text", rest]] if rest else "`/note` needs text."
    if verb == "resolve":
        return [move("RESOLVED", rest)] if rest else "`/resolve` needs a reason."
    if verb == "close":
        return [move("CLOSED", rest or "closed")]
    if verb == "reopen":
        return [move("ACTIVE", rest)] if rest else "`/reopen` needs a reason."
    return HELP


def cmd_command(store: Store, root: Path, text: str, issue: str, author: str) -> int:
    if author != OWNER:  # defence in depth; the workflow already filters
        _out(reply="Ignored: only the repo owner's commands are obeyed.", close="false")
        return 0
    links = _json_file(root / "issues.json", {})
    incident_id = next((inc for inc, num in links.items() if str(num) == str(issue)), None)
    if not incident_id:
        _out(reply="This issue is not linked to an incident.", close="false")
        return 0
    state_before = store.get_incident(incident_id).current_state.value
    plan = plan_command(text, incident_id, issue, state_before)
    if plan == "Not a command.":  # an ordinary comment that merely contains a "/": stay silent
        _out(reply="", close="false")
        return 0
    if isinstance(plan, str):
        _out(reply=plan, close="false")
        return 0
    results = []
    for argv in plan:
        code, output = _run_cli(["--root", str(root), *argv])
        results.append(f"`{argv[0]}` → {'ok' if code == 0 else 'refused'}: {output or '(no output)'}")
        if code != 0:
            break
    state = store.get_incident(incident_id).current_state.value
    _out(reply="\n".join(results) + f"\n\nState now **{state}**. Next: {NEXT_STEP.get(state, '`/help`')}.",
         close="true" if state == "CLOSED" else "false")
    return 0


def cmd_guard(store: Store, root: Path, issue: str) -> int:
    """An incident issue was closed with GitHub's button. The agent's record is the source of truth: if the
    incident is not CLOSED, ask the workflow to reopen the issue and say what to do instead."""
    links = _json_file(root / "issues.json", {})
    incident_id = next((inc for inc, num in links.items() if str(num) == str(issue)), None)
    if not incident_id:
        _out(reopen="false", reply="")
        return 0
    state = store.get_incident(incident_id).current_state.value
    if state == "CLOSED":
        _out(reopen="false", reply="")
        return 0
    _out(reopen="true", reply=(
        f"Reopened: closing the issue does not close the incident. `{incident_id}` is still **{state}** in the "
        f"incident record, which is the source of truth.\n\nNext: {NEXT_STEP.get(state, '`/help`')}. "
        "The issue closes itself when you reach `/close`."))
    return 0


# ---------------------------------------------------------------- feed

def gate_label(incident) -> str:
    for event in reversed(incident.timeline):
        if event.event_type == "triage_rejected":
            return "rejected by human"
        if event.event_type == "triage_applied":
            return "approved by human" if event.approved_by else "auto-applied (low risk, high confidence)"
        if event.event_type == "ai_triage_proposed":
            return "awaiting human" if event.requires_approval else "auto-applied (low risk, high confidence)"
        if event.event_type == "triage_failed":
            return "model unavailable; human triage"
    return "not triaged"


def actor_kind(actor: str) -> str:
    return "human" if actor.startswith("human:") else "ai" if actor.startswith("ai:") else "service" if actor.startswith("service:") else "other"


def cmd_feed(store: Store, root: Path, repo: str) -> int:
    links = _json_file(root / "issues.json", {})
    site = _json_file(root / "site_state.json", {})
    incidents = sorted((store.get_incident(r["id"]) for r in store.summaries()), key=lambda i: i.created_at, reverse=True)
    feed = {"generated_at": _now(), "repo": repo, "incidents": []}
    for inc in incidents[:FEED_LIMIT]:
        t = inc.ai_triage
        events = [e for e in inc.timeline if e.event_type != "metric"]
        timeline = events if len(events) <= 12 else [events[0], *events[-11:]]  # always keep who raised it
        feed["incidents"].append({
            "id": inc.id,
            "title": _clip(inc.title, 160),
            "state": inc.current_state.value,
            "priority": inc.priority,
            "created_at": inc.created_at.isoformat(timespec="seconds"),
            "updated_at": inc.updated_at.isoformat(timespec="seconds"),
            "triage": None if not t else {"priority": t.priority, "confidence": round(t.confidence, 2), "reasoning": _clip(t.reasoning, 280)},
            "gate": gate_label(inc),
            "drafts_unsent": len(inc.communications),
            "gaps": len(inc.detection_gaps),
            "recovered_at": site.get(inc.id, {}).get("recovered_at"),
            "issue_url": f"https://github.com/{repo}/issues/{links[inc.id]}" if inc.id in links else None,
            "timeline": [
                {"at": e.timestamp.isoformat(timespec="seconds"), "kind": actor_kind(e.actor), "event": e.event_type,
                 "to": e.to_state.value if e.to_state else None}
                for e in timeline
            ],
        })
    (root / "feed.json").write_text(json.dumps(feed, indent=2), encoding="utf-8")
    print(f"feed: {len(feed['incidents'])} incidents")
    return 0


def cmd_link(root: Path, incident_id: str, issue: str) -> int:
    links = _json_file(root / "issues.json", {})
    links[incident_id] = int(issue)
    (root / "issues.json").write_text(json.dumps(links, indent=2), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="site_bridge.py")
    p.add_argument("--root", required=True, help="incident store (the incident-data branch checkout)")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "vikiscoding/vikrant_perswebsite_incidents_aiengine"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("alert"); sub.add_parser("recovered"); sub.add_parser("feed")
    c = sub.add_parser("command"); c.add_argument("--issue", required=True); c.add_argument("--author", required=True)
    l = sub.add_parser("link"); l.add_argument("--incident", required=True); l.add_argument("--issue", required=True)
    g = sub.add_parser("guard"); g.add_argument("--issue", required=True)
    args = p.parse_args(argv)
    root = Path(args.root)
    store = Store(root)
    if args.cmd == "alert":
        return cmd_alert(store, os.environ.get("ALERT_PAYLOAD", ""))
    if args.cmd == "recovered":
        return cmd_recovered(store, root, os.environ.get("ALERT_PAYLOAD", ""))
    if args.cmd == "command":
        return cmd_command(store, root, os.environ.get("COMMENT_BODY", ""), args.issue, args.author)
    if args.cmd == "link":
        return cmd_link(root, args.incident, args.issue)
    if args.cmd == "guard":
        return cmd_guard(store, root, args.issue)
    return cmd_feed(store, root, args.repo)


if __name__ == "__main__":
    raise SystemExit(main())
