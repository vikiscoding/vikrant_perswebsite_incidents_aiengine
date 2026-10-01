import json
from pathlib import Path

import pytest

from cmdb import Cmdb, ConfigurationItem
from ingest import IngestError, ingest_alert, ingest_manual
from models import IncidentState
from org import OWNING_TEAMS
from store import Store

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ACTOR = "human:vikrant"


@pytest.fixture
def cmdb() -> Cmdb:
    return Cmdb.load()


def test_cmdb_matches_owning_teams(cmdb: Cmdb):
    assert {item.owner_team for item in cmdb.items} == OWNING_TEAMS
    web = cmdb.find("website-web")
    assert web is not None
    assert web.owner_team == "Application"
    assert cmdb.find("CI-APP-001").ci_id == web.ci_id


def test_unknown_owner_team_rejected():
    with pytest.raises(Exception):
        ConfigurationItem(
            ci_id="CI-X",
            name="rogue",
            type="Application",
            environment="Production",
            status="Operational",
            criticality="Low",
            owner_team="Finance",
            technical_contact="x",
            depends_on=[],
        )


def test_ingest_alert_and_manual_are_comparable(tmp_path, cmdb: Cmdb):
    store = Store(tmp_path)
    alert = json.loads((FIXTURES / "alert_website_5xx.json").read_text(encoding="utf-8"))
    manual = json.loads((FIXTURES / "manual_checkout_report.json").read_text(encoding="utf-8"))

    a = ingest_alert(store, alert, ACTOR, cmdb)
    m = ingest_manual(store, manual, ACTOR, cmdb)

    for incident in (a, m):
        assert incident.current_state is IncidentState.DETECTED
        assert incident.priority is None
        assert incident.cmdb_snapshot["matched"]
        assert incident.cmdb_snapshot["routing_hint"] == "Application"
        assert (tmp_path / "incidents" / incident.id / "raw_inputs" / "intake.json").is_file()

    assert a.source == "alert"
    assert m.source == "manual"
    assert a.affected_services == ["website-web"]
    assert m.affected_services == ["checkout-api"]
    assert a.affected_ci_ids[0] == "CI-APP-001"
    assert m.affected_ci_ids[0] == "CI-APP-003"
    assert a.cmdb_snapshot["primary_ci_id"] == "CI-APP-001"
    assert "CI-APP-002" in a.affected_ci_ids
    assert any(dep["ci_id"] == "CI-APP-002" for dep in a.cmdb_snapshot["dependencies"])
    assert any(dep["ci_id"] == "CI-PLT-001" for dep in a.cmdb_snapshot["dependencies_indirect"])
    assert m.cmdb_snapshot["affected_ci_ids"] == m.affected_ci_ids


def test_claimed_priority_is_ignored(tmp_path, cmdb: Cmdb):
    store = Store(tmp_path)
    payload = {
        "reporter": "human:support-l1",
        "title": "Site looks slow",
        "description": "A user complained.",
        "affected_service": "website-web",
        "claimed_priority": "Critical",
    }
    incident = ingest_manual(store, payload, ACTOR, cmdb)
    assert incident.priority is None


def test_alert_severity_is_not_priority(tmp_path, cmdb: Cmdb):
    store = Store(tmp_path)
    payload = {
        "monitor": "cdn-origin-errors",
        "service": "cdn",
        "message": "origin fetch errors",
        "severity": "critical",
    }
    incident = ingest_alert(store, payload, ACTOR, cmdb)
    assert incident.priority is None
    assert incident.cmdb_snapshot["routing_hint"] == "Edge"


def test_unknown_service_still_creates_incident(tmp_path, cmdb: Cmdb):
    store = Store(tmp_path)
    incident = ingest_alert(
        store,
        {"monitor": "mystery", "service": "not-a-ci", "message": "something broke"},
        ACTOR,
        cmdb,
    )
    assert incident.current_state is IncidentState.DETECTED
    assert incident.cmdb_snapshot["matched"] == []
    assert incident.cmdb_snapshot["unknown_service"] == "not-a-ci"
    assert incident.affected_ci_ids == []
    assert incident.cmdb_snapshot["primary_ci_id"] is None


def test_postgres_snapshot_includes_used_by(cmdb: Cmdb):
    snapshot = cmdb.snapshot_for("postgres-primary")
    assert snapshot["primary_ci_id"] == "CI-DATA-001"
    used = {row["ci_id"] for row in snapshot["used_by"]}
    assert "CI-APP-003" in used
    assert "CI-DATA-002" in used
    assert snapshot["affected_ci_ids"][0] == "CI-DATA-001"
    assert "CI-APP-003" in snapshot["affected_ci_ids"]


def test_invalid_payload_rejected(tmp_path, cmdb: Cmdb):
    store = Store(tmp_path)
    with pytest.raises(IngestError):
        ingest_alert(store, {"monitor": "only-monitor"}, ACTOR, cmdb)
    with pytest.raises(IngestError):
        ingest_manual(store, {"title": "no reporter"}, ACTOR, cmdb)
