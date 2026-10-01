from pathlib import Path

from company import Company, CompanyConfigError, IntakeSource, Team, TransitionRule, load_company, reset_company
from ingest import IngestError, ingest
from store import Store
from cmdb import Cmdb, ConfigurationItem
from transitions import can_transition

HUMAN = "human:vikrant"
AI = "ai:grok:grok-4"


def _minimal_company(**overrides) -> Company:
    payload = dict(
        name="Acme",
        kind="internal IT",
        description="One-team shop",
        cmdb_path=Path("mock_cmdb.json"),
        teams=(Team(name="IT", description="Everything"),),
        states=("OPEN", "DONE"),
        start_state="OPEN",
        transitions=(
            TransitionRule(from_state="OPEN", to_state="DONE", requires_human="always"),
        ),
        intake=(
            IntakeSource(
                id="chat",
                required=("who", "text"),
                optional=(),
                service_field=None,
                title_template=None,
                title_field="text",
                reporter_template=None,
                reporter_field="who",
                untrusted_priority_fields=(),
            ),
        ),
    )
    payload.update(overrides)
    return Company(**payload)


def test_default_company_is_northstar():
    from company import get_company

    cfg = get_company()
    assert cfg.name == "Northstar"
    assert "Application" in cfg.owning_teams()
    assert cfg.start_state == "DETECTED"
    assert cfg.intake_source("alert") is not None
    assert cfg.intake_source("manual") is not None


def test_custom_lifecycle_table(monkeypatch):
    acme = _minimal_company()
    assert can_transition("OPEN", "DONE", HUMAN, company=acme).allowed
    assert can_transition("OPEN", "DONE", AI, company=acme).allowed is False
    assert can_transition("DONE", "OPEN", HUMAN, company=acme).allowed is False
    assert can_transition("DETECTED", "TRIAGING", HUMAN, company=acme).allowed is False


def test_load_rejects_empty_teams(tmp_path):
    path = tmp_path / "company.toml"
    path.write_text(
        """
[company]
name = "X"
kind = "y"

[lifecycle]
states = ["A"]
start_state = "A"

[[lifecycle.transitions]]
from = "A"
to = "A"
requires_human = "never"

[[intake]]
id = "x"
required = ["title"]
title_field = "title"
reporter_field = "title"
""",
        encoding="utf-8",
    )
    try:
        load_company(path)
        assert False, "expected CompanyConfigError"
    except CompanyConfigError as exc:
        assert "teams" in str(exc)


def test_extra_intake_source(tmp_path, monkeypatch):
    src = Path(__file__).resolve().parent.parent / "company.toml"
    cmdb_abs = (src.parent / "mock_cmdb.json").resolve().as_posix()
    text = src.read_text(encoding="utf-8").replace('cmdb = "mock_cmdb.json"', f'cmdb = "{cmdb_abs}"')
    text += """

[[intake]]
id = "statuspage"
required = ["component", "body"]
service_field = "component"
title_template = "statuspage: {body}"
reporter_template = "statuspage:{component}"
untrusted_priority_fields = ["severity"]
"""
    path = tmp_path / "company.toml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("INCIDENT_COMPANY_FILE", str(path))
    reset_company()
    try:
        store = Store(tmp_path / "data")
        cmdb = Cmdb.load()
        incident = ingest(
            store,
            "statuspage",
            {"component": "website-web", "body": "degraded performance", "severity": "critical"},
            HUMAN,
            cmdb,
        )
        assert incident.source == "statuspage"
        assert incident.priority is None
        assert incident.affected_services == ["website-web"]
        assert incident.cmdb_snapshot["routing_hint"] == "Application"
    finally:
        monkeypatch.delenv("INCIDENT_COMPANY_FILE", raising=False)
        reset_company()


def test_unknown_intake_rejected(tmp_path):
    store = Store(tmp_path)
    cmdb = Cmdb([
        ConfigurationItem(
            ci_id="CI-1",
            name="website-web",
            type="Application",
            environment="Production",
            status="Operational",
            criticality="Critical",
            owner_team="Application",
            technical_contact="x",
            depends_on=[],
        )
    ])
    try:
        ingest(store, "carrier-pigeon", {"title": "nope"}, HUMAN, cmdb)
        assert False, "expected IngestError"
    except IngestError as exc:
        assert "unknown intake source" in str(exc)
