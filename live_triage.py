"""Thin alias: ingest the 5xx fixture then `cli.py propose`. Prefer the CLI."""

import json
import os
from pathlib import Path

from cli import run_propose
from cmdb import Cmdb
from grok import GrokClient
from ingest import ingest_alert
from store import Store

ROOT = Path(__file__).resolve().parent
ACTOR = "human:vikrant"


def main() -> None:
    if not os.environ.get("XAI_API_KEY"):
        raise SystemExit("XAI_API_KEY is not set in this shell. Set it, then rerun.")

    store = Store(ROOT)
    alert = json.loads((ROOT / "fixtures" / "alert_website_5xx.json").read_text(encoding="utf-8"))
    incident = ingest_alert(store, alert, ACTOR, Cmdb.load())
    grok = GrokClient(store)
    try:
        result = run_propose(store, grok, incident.id)
    finally:
        grok.close()
    triage = result["triage"]
    print(f"incident     {result['incident'].id}")
    print(f"state        {result['incident'].current_state.value}")
    print(f"applied      {triage.applied}")
    print(f"needs_human  {triage.requires_approval}")
    print(f"priority_now {result['incident'].priority!r}")
    print(f"error        {triage.error!r}")
    print(f"comms        {len(result['incident'].communications)}")
    print(f"gaps         {len(result['incident'].detection_gaps)}")
    print("prefer: python cli.py ingest ... && python cli.py propose --id <id>")


if __name__ == "__main__":
    main()
