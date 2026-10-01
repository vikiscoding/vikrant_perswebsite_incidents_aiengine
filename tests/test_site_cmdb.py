"""vikrantsingh.fyi is a real CI: alerts from the site get an owner, a blast radius and a runbook hint (game day 1)."""
from cmdb import Cmdb


def test_site_alert_resolves_owner_and_dependencies():
    snap = Cmdb.load().snapshot_for("vikrantsingh.fyi")
    assert snap["matched"] and snap["matched"][0]["ci_id"] == "CI-SITE-001"
    assert snap["routing_hint"] == "Application"
    deps = {d["ci_id"] for d in snap["dependencies"]} | {d["ci_id"] for d in snap["dependencies_indirect"]}
    assert {"CI-SITE-002", "CI-SITE-003", "CI-SITE-004"} <= deps
