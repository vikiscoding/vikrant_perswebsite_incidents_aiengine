"""Human-in-the-loop CLI. Mutating commands require --actor human:<id>."""

import argparse
import json
import sys
import uuid
from pathlib import Path

from cmdb import Cmdb
from comms import draft_ack_and_status
from gaps import analyze_gaps
from grok import GrokClient
from handoff import assign, release, require_typed_confirm, route, assert_can_act
from ingest import ingest
from models import IncidentEvent, is_human_actor
from store import Store, StoreError, _utcnow
from triage import approve_triage, override_triage, reject_triage, run_triage


def _store(root: str) -> Store:
    return Store(root)


def _grok(store: Store) -> GrokClient:
    return GrokClient(store, progress=True)


def _print_incident(incident) -> None:
    print(f"id        {incident.id}")
    print(f"state     {incident.current_state.value}")
    print(f"priority  {incident.priority}")
    print(f"impact    {incident.impact_score}")
    print(f"title     {incident.title}")
    print(f"services  {incident.affected_services}")
    print(f"cis       {incident.affected_ci_ids}")
    print(f"route     {(incident.cmdb_snapshot or {}).get('routing_hint')}")
    print(f"group     {incident.support_group}")
    print(f"holder    {incident.assigned_to}")
    if incident.ai_triage:
        print(f"ai_triage {incident.ai_triage.priority} conf={incident.ai_triage.confidence} route={incident.ai_triage.routing_suggestion}")
        print(f"reasoning {incident.ai_triage.reasoning}")
    print("communications:")
    if not incident.communications:
        print("  (none)")
    for draft in incident.communications:
        print(f"  [{draft.audience}] {draft.channel}  sent=false")
        print(f"  subject: {draft.subject}")
        print(f"  body: {draft.body}")
    print("detection_gaps:")
    if not incident.detection_gaps:
        print("  (none)")
    for gap in incident.detection_gaps:
        print(f"  - {gap.severity} {gap.status}: {gap.gap_description}")
        print(f"    evidence: {gap.evidence}")
    print("timeline:")
    for event in incident.timeline:
        extra = event.to_state.value if event.to_state else event.event_type
        print(f"  {event.timestamp.isoformat()}  {event.actor}  {event.event_type}  {extra}")


def run_propose(store: Store, grok: GrokClient, incident_id: str) -> dict:
    triage = run_triage(store, grok, incident_id)
    ack, status = draft_ack_and_status(store, grok, incident_id)
    gaps = analyze_gaps(store, grok, incident_id)
    incident = store.get_incident(incident_id)
    sent = [
        event.payload.get("sent")
        for event in incident.timeline
        if event.event_type == "communication_drafted" and event.payload
    ]
    return {
        "incident": incident,
        "triage": triage,
        "ack": ack,
        "status": status,
        "gaps": gaps,
        "any_sent": any(sent),
    }


def cmd_ingest(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    incident = ingest(_store(args.root), args.source, payload, args.actor, Cmdb.load())
    print(incident.id)
    print(incident.current_state.value)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = _store(args.root)
    if not args.id:
        for row in store.summaries():
            print(f"{row['id']}  {row['current_state']:12}  pri={row['priority']!s:8}  {row['title']}")
        return 0
    _print_incident(store.get_incident(args.id))
    print(f"folder    {store.incident_dir(args.id)}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    incident = approve_triage(_store(args.root), args.id, args.actor)
    print(incident.priority)
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    incident = reject_triage(_store(args.root), args.id, args.actor, args.reason)
    print(incident.priority)
    return 0


def cmd_override(args: argparse.Namespace) -> int:
    value: object = args.value
    if args.field == "impact_score":
        value = int(args.value)
    incident = override_triage(_store(args.root), args.id, args.actor, args.field, value, args.reason)
    print(getattr(incident, args.field))
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    store = _store(args.root)
    store.append_event(
        args.id,
        IncidentEvent(
            id=f"evt-{uuid.uuid4().hex[:12]}",
            timestamp=_utcnow(),
            actor=args.actor,
            event_type="note",
            reasoning=args.text,
        ),
    )
    print("ok")
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    store = _store(args.root)
    if is_human_actor(args.actor):
        require_typed_confirm(args.to, args.confirm)
        current = store.get_incident(args.id)
        assert_can_act(current, args.actor, steal=bool(args.steal))
    incident = store.transition(args.id, args.to, args.actor, args.reason)
    print(incident.current_state.value)
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    incident = assign(_store(args.root), args.id, args.actor, args.to, args.reason, steal=bool(args.steal))
    print(incident.assigned_to)
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    require_typed_confirm("RELEASE", args.confirm)
    incident = release(_store(args.root), args.id, args.actor, args.reason)
    print(incident.assigned_to)
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    require_typed_confirm(args.group, args.confirm)
    incident = route(_store(args.root), args.id, args.actor, args.group, args.reason)
    print(incident.support_group)
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    store = _store(args.root)
    grok = _grok(store)
    try:
        result = run_propose(store, grok, args.id)
    finally:
        grok.close()
    incident = result["incident"]
    triage = result["triage"]
    print(f"id           {incident.id}")
    print(f"state        {incident.current_state.value}")
    print(f"applied      {triage.applied}")
    print(f"needs_human  {triage.requires_approval}")
    print(f"priority_now {incident.priority!r}")
    print(f"triage_error {triage.error!r}")
    print(f"comms        {len(incident.communications)} sent={result['any_sent']}")
    print(f"gaps         {len(incident.detection_gaps)} added={len(result['gaps'].added)}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    store = _store(args.root)
    text = store.get_incident(args.id).model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="Incident-AI operator CLI")
    parser.add_argument("--root", default=".", help="store root (default: current directory)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ingest_p = sub.add_parser("ingest", help="ingest alert or manual JSON")
    ingest_p.add_argument("--source", required=True, choices=["alert", "manual"])
    ingest_p.add_argument("--file", required=True)
    ingest_p.add_argument("--actor", required=True)
    ingest_p.set_defaults(func=cmd_ingest)

    show_p = sub.add_parser("show", help="list incidents or show one")
    show_p.add_argument("id", nargs="?", default=None)
    show_p.set_defaults(func=cmd_show)

    propose_p = sub.add_parser("propose", help="triage + ack/status drafts + gaps (never sent)")
    propose_p.add_argument("--id", required=True)
    propose_p.set_defaults(func=cmd_propose)

    approve_p = sub.add_parser("approve", help="approve gated AI triage")
    approve_p.add_argument("--id", required=True)
    approve_p.add_argument("--actor", required=True)
    approve_p.set_defaults(func=cmd_approve)

    reject_p = sub.add_parser("reject", help="reject AI triage")
    reject_p.add_argument("--id", required=True)
    reject_p.add_argument("--actor", required=True)
    reject_p.add_argument("--reason", required=True)
    reject_p.set_defaults(func=cmd_reject)

    override_p = sub.add_parser("override", help="override priority|impact_score|assigned_to")
    override_p.add_argument("--id", required=True)
    override_p.add_argument("--actor", required=True)
    override_p.add_argument("--field", required=True, choices=["priority", "impact_score", "assigned_to"])
    override_p.add_argument("--value", required=True)
    override_p.add_argument("--reason", required=True)
    override_p.set_defaults(func=cmd_override)

    note_p = sub.add_parser("note", help="append a human note")
    note_p.add_argument("--id", required=True)
    note_p.add_argument("--actor", required=True)
    note_p.add_argument("--text", required=True)
    note_p.set_defaults(func=cmd_note)

    trans_p = sub.add_parser("transition", help="legal state change")
    trans_p.add_argument("--id", required=True)
    trans_p.add_argument("--to", required=True)
    trans_p.add_argument("--actor", required=True)
    trans_p.add_argument("--reason", required=True)
    trans_p.add_argument("--confirm", default=None, help="human must type the target state")
    trans_p.add_argument("--steal", action="store_true", help="act while another human holds the incident")
    trans_p.set_defaults(func=cmd_transition)

    assign_p = sub.add_parser("assign", help="hold the incident (traced)")
    assign_p.add_argument("--id", required=True)
    assign_p.add_argument("--actor", required=True)
    assign_p.add_argument("--to", required=True)
    assign_p.add_argument("--reason", required=True)
    assign_p.add_argument("--steal", action="store_true")
    assign_p.set_defaults(func=cmd_assign)

    release_p = sub.add_parser("release", help="drop the hold; type RELEASE")
    release_p.add_argument("--id", required=True)
    release_p.add_argument("--actor", required=True)
    release_p.add_argument("--reason", required=True)
    release_p.add_argument("--confirm", required=True, help="must be RELEASE")
    release_p.set_defaults(func=cmd_release)

    route_p = sub.add_parser("route", help="change support group (traced)")
    route_p.add_argument("--id", required=True)
    route_p.add_argument("--actor", required=True)
    route_p.add_argument("--group", required=True)
    route_p.add_argument("--reason", required=True)
    route_p.add_argument("--confirm", required=True, help="must equal --group")
    route_p.set_defaults(func=cmd_route)

    export_p = sub.add_parser("export", help="write incident JSON")
    export_p.add_argument("--id", required=True)
    export_p.add_argument("--out", default=None)
    export_p.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (StoreError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
