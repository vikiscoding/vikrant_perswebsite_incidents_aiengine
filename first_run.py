"""First run: ingest configured intake sources for the loaded company."""

import json
from pathlib import Path

from cmdb import Cmdb
from company import get_company
from ingest import ingest_alert, ingest_manual
from store import Store

ROOT = Path(__file__).resolve().parent
ACTOR = "human:vikrant"


def main() -> None:
    cfg = get_company()
    cmdb = Cmdb.load()
    store = Store(ROOT)
    print(
        f"{cfg.name} ({cfg.kind}) first run — {len(cmdb.items)} CIs, "
        f"teams: {', '.join(cfg.team_map())}"
    )

    alert = json.loads((ROOT / "fixtures" / "alert_website_5xx.json").read_text(encoding="utf-8"))
    manual = json.loads((ROOT / "fixtures" / "manual_checkout_report.json").read_text(encoding="utf-8"))

    a = ingest_alert(store, alert, ACTOR, cmdb)
    m = ingest_manual(store, manual, ACTOR, cmdb)

    for incident in (a, m):
        folder = store.incident_dir(incident.id)
        hint = incident.cmdb_snapshot.get("routing_hint")
        print(
            f"{incident.id}  {incident.source:6}  {incident.current_state.value:9}  "
            f"route={hint}  services={incident.affected_services}  "
            f"cis={incident.affected_ci_ids}  "
            f"priority={incident.priority!r}  folder={folder}"
        )


if __name__ == "__main__":
    main()
