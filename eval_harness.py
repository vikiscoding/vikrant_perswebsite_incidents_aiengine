"""Replay eval fixtures. Scores are computed from ground truth — the model does not grade itself."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

import httpx

from cmdb import Cmdb
from comms import draft_ack_and_status
from gaps import analyze_gaps
from grok import GrokClient
from ingest import ingest
from store import Store
from triage import run_triage

ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = ROOT / "fixtures" / "eval"
PRIORITY_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
ACTOR = "human:eval"


def _load_fixtures() -> list[dict[str, Any]]:
    files = sorted(FIXTURE_DIR.glob("*.json"))
    return [json.loads(path.read_text(encoding="utf-8")) for path in files]


def _scripted_client(store: Store, replies: list[dict[str, Any]]) -> GrokClient:
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            return httpx.Response(500, text="scripted grok exhausted")
        body = queue.pop(0)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    return GrokClient(
        store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        api_key="eval-scripted",
        model="scripted",
    )


def _score_triage(proposal: Optional[dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
    if not proposal:
        return {"score": 1, "priority_correct": False, "impact_ok": False, "routing_ok": False, "correct_or_better": False}
    gt_pri = truth["priority"]
    got_pri = proposal.get("priority")
    rank_ok = PRIORITY_RANK.get(got_pri, -1) >= PRIORITY_RANK.get(gt_pri, 99)
    exact = got_pri == gt_pri
    gt_impact = int(truth["impact_score"])
    got_impact = int(proposal.get("impact_score") or 0)
    impact_ok = abs(got_impact - gt_impact) / max(gt_impact, 1) <= 0.20
    routing_ok = proposal.get("routing_suggestion") == truth.get("routing_suggestion")
    if exact and impact_ok and routing_ok:
        score = 5
    elif exact and (impact_ok or routing_ok):
        score = 4
    elif exact or rank_ok:
        score = 3
    elif impact_ok or routing_ok:
        score = 2
    else:
        score = 1
    return {
        "score": score,
        "priority_correct": exact,
        "impact_ok": impact_ok,
        "routing_ok": routing_ok,
        "correct_or_better": exact or rank_ok,
    }


def _score_comms(incident) -> dict[str, Any]:
    if len(incident.communications) >= 2:
        return {"score": 4, "drafts": len(incident.communications), "note": "ack+status present; tone is human-scored later"}
    if incident.communications:
        return {"score": 3, "drafts": len(incident.communications), "note": "only one draft"}
    return {"score": 1, "drafts": 0, "note": "no drafts"}


def _score_gaps(incident, truth: dict[str, Any]) -> dict[str, Any]:
    live = [gap for gap in incident.detection_gaps if gap.status != "rejected" and gap.evidence]
    hm = [gap for gap in live if gap.severity in {"High", "Medium"}]
    need = int(truth.get("gaps_min_high_medium") or 0)
    if need == 0:
        score = 4 if not hm else 3
    elif len(hm) >= need:
        score = 4
    elif live:
        score = 3
    else:
        score = 1
    return {"score": score, "high_medium": len(hm), "total": len(live)}


def _score_logging(store: Store, incident) -> dict[str, Any]:
    traces = list((store.incident_dir(incident.id) / "ai_traces").glob("*.json"))
    ai_calls = [event for event in incident.timeline if event.event_type == "ai_call"]
    actors_ok = all(event.actor for event in incident.timeline)
    traces_ok = len(traces) >= len(ai_calls) and all(ai_calls)
    passed = bool(traces) and actors_ok and len(ai_calls) == len(traces)
    return {
        "pass": passed,
        "score": 5 if passed else 1,
        "trace_count": len(traces),
        "ai_call_events": len(ai_calls),
        "trace_paths": [f"ai_traces/{path.name}" for path in traces],
    }


def _run_one(store: Store, fixture: dict[str, Any], live: bool, id_map: dict[str, str]) -> dict[str, Any]:
    cmdb = Cmdb.load()
    incident = ingest(store, fixture["source"], fixture["input"], ACTOR, cmdb)
    id_map[fixture["id"]] = incident.id
    mock = dict(fixture.get("mock") or {})
    if truth_dup := fixture.get("ground_truth", {}).get("duplicate_same_as"):
        if truth_dup in id_map and "triage" in mock:
            mock["triage"] = {**mock["triage"], "duplicate_of": id_map[truth_dup]}
    if live:
        grok = GrokClient(store)
    else:
        replies = [mock["triage"], mock["ack"], mock["status"], mock["gaps"]]
        grok = _scripted_client(store, replies)
    try:
        triage = run_triage(store, grok, incident.id)
        draft_ack_and_status(store, grok, incident.id)
        analyze_gaps(store, grok, incident.id)
    finally:
        grok.close()

    loaded = store.get_incident(incident.id)
    truth = fixture["ground_truth"]
    proposal = loaded.ai_triage.model_dump(mode="json") if loaded.ai_triage else None
    if truth.get("duplicate_same_as"):
        expected_dup = id_map.get(truth["duplicate_same_as"])
        truth = {**truth, "duplicate_of": expected_dup}

    triage_s = _score_triage(proposal, truth)
    dup_ok = True
    if truth.get("duplicate_of"):
        dup_ok = bool(proposal and proposal.get("duplicate_of") == truth["duplicate_of"])
        if not dup_ok:
            triage_s["score"] = min(triage_s["score"], 3)
    comms_s = _score_comms(loaded)
    gaps_s = _score_gaps(loaded, truth)
    log_s = _score_logging(store, loaded)
    utility = round((triage_s["score"] + comms_s["score"] + gaps_s["score"] + log_s["score"]) / 4, 2)
    return {
        "fixture_id": fixture["id"],
        "incident_id": loaded.id,
        "proposal": proposal,
        "ground_truth": truth,
        "scores": {
            "triage_quality": triage_s,
            "communication": comms_s,
            "detection_gaps": gaps_s,
            "logging_completeness": log_s,
            "overall_utility": utility,
        },
        "duplicate_ok": dup_ok,
        "notes": "Deterministic harness scores vs ground truth. Not model self-eval.",
    }


def run_harness(out_dir: Path, live: bool = False) -> dict[str, Any]:
    fixtures = _load_fixtures()
    if len(fixtures) < 8:
        raise SystemExit(f"need at least 8 fixtures, found {len(fixtures)}")
    store = Store(out_dir / "work")
    id_map: dict[str, str] = {}
    results = [_run_one(store, fixture, live, id_map) for fixture in fixtures]
    utilities = [row["scores"]["overall_utility"] for row in results]
    triage_scores = [row["scores"]["triage_quality"]["score"] for row in results]
    cob = [row["scores"]["triage_quality"]["correct_or_better"] for row in results]
    hm_gaps = sum(row["scores"]["detection_gaps"]["high_medium"] for row in results)
    logging_all = all(row["scores"]["logging_completeness"]["pass"] for row in results)
    dims = ["triage_quality", "communication", "detection_gaps", "logging_completeness"]
    dim_avgs = {
        name: round(sum(row["scores"][name]["score"] for row in results) / len(results), 2)
        for name in dims
    }
    summary = {
        "date": date.today().isoformat(),
        "mode": "live" if live else "scripted",
        "n": len(results),
        "averages": {**dim_avgs, "overall_utility": round(sum(utilities) / len(utilities), 2)},
        "triage_correct_or_better_pct": round(100 * sum(cob) / len(cob), 1),
        "high_medium_gaps_total": hm_gaps,
        "logging_all_pass": logging_all,
        "phase1_floors": {
            "overall_utility_ge_3_8": (sum(utilities) / len(utilities)) >= 3.8,
            "no_dimension_below_3": all(avg >= 3.0 for avg in dim_avgs.values()),
            "logging_pass_all": logging_all,
            "triage_correct_or_better_ge_70": (sum(cob) / len(cob)) >= 0.70,
            "high_medium_gaps_ge_5": hm_gaps >= 5,
        },
        "results": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for row in results:
        (out_dir / f"{row['fixture_id']}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Incident-AI evaluation harness")
    parser.add_argument("--live", action="store_true", help="call real Grok (quality run)")
    parser.add_argument("--out", default="", help="output directory (default evaluations/YYYY-MM-DD)")
    args = parser.parse_args(argv)
    dest = Path(args.out) if args.out else ROOT / "evaluations" / date.today().isoformat()
    summary = run_harness(dest, live=args.live)
    floors = summary["phase1_floors"]
    print(f"wrote {dest / 'summary.json'}")
    print(f"n={summary['n']} overall={summary['averages']['overall_utility']} cob={summary['triage_correct_or_better_pct']}% gaps={summary['high_medium_gaps_total']}")
    print("floors", floors)
    return 0 if all(floors.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
