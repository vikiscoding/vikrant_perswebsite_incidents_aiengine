from pathlib import Path

from cli import main
from store import Store

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "alert_website_5xx.json"
HUMAN = "human:vikrant"
OTHER = "human:priya"


def _run(root: Path, *argv: str) -> tuple[int, str]:
    import io
    import sys

    buf = io.StringIO()
    err = io.StringIO()
    old, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = buf, err
    try:
        code = main(["--root", str(root), *argv])
    finally:
        sys.stdout, sys.stderr = old, old_e
    return code, buf.getvalue() + err.getvalue()


def _ingest(tmp_path: Path) -> str:
    code, out = _run(tmp_path, "ingest", "--source", "alert", "--file", str(FIXTURE), "--actor", HUMAN)
    assert code == 0
    return out.splitlines()[0].strip()


def test_human_transition_requires_typed_state(tmp_path):
    incident_id = _ingest(tmp_path)
    code, err = _run(tmp_path, "transition", "--id", incident_id, "--to", "TRIAGING", "--actor", HUMAN, "--reason", "go")
    assert code == 1
    assert "confirm" in err.lower()
    code, out = _run(
        tmp_path, "transition", "--id", incident_id, "--to", "TRIAGING", "--actor", HUMAN, "--reason", "go", "--confirm", "TRIAGING"
    )
    assert code == 0
    assert "TRIAGING" in out


def test_holder_must_release_before_someone_else_moves(tmp_path):
    incident_id = _ingest(tmp_path)
    assert _run(tmp_path, "assign", "--id", incident_id, "--actor", HUMAN, "--to", HUMAN, "--reason", "mine")[0] == 0
    code, err = _run(
        tmp_path,
        "transition",
        "--id",
        incident_id,
        "--to",
        "TRIAGING",
        "--actor",
        OTHER,
        "--reason",
        "take",
        "--confirm",
        "TRIAGING",
    )
    assert code == 1
    assert "held by" in err
    code, err = _run(tmp_path, "release", "--id", incident_id, "--actor", HUMAN, "--reason", "done", "--confirm", "nope")
    assert code == 1
    assert _run(tmp_path, "release", "--id", incident_id, "--actor", HUMAN, "--reason", "shift end", "--confirm", "RELEASE")[0] == 0
    assert Store(tmp_path).get_incident(incident_id).assigned_to is None
    assert _run(
        tmp_path, "transition", "--id", incident_id, "--to", "TRIAGING", "--actor", OTHER, "--reason", "pickup", "--confirm", "TRIAGING"
    )[0] == 0


def test_support_group_change_is_traced(tmp_path):
    incident_id = _ingest(tmp_path)
    incident = Store(tmp_path).get_incident(incident_id)
    assert incident.support_group == "Application"
    code, err = _run(
        tmp_path, "route", "--id", incident_id, "--actor", HUMAN, "--group", "Data", "--reason", "db", "--confirm", "Edge"
    )
    assert code == 1
    assert _run(
        tmp_path, "route", "--id", incident_id, "--actor", HUMAN, "--group", "Data", "--reason", "looks like postgres", "--confirm", "Data"
    )[0] == 0
    loaded = Store(tmp_path).get_incident(incident_id)
    assert loaded.support_group == "Data"
    changes = [event for event in loaded.timeline if event.event_type == "support_group_changed"]
    assert len(changes) == 1
    assert changes[0].payload["from"] == "Application"
    assert changes[0].payload["to"] == "Data"
    assert changes[0].payload["reason"] == "looks like postgres"
    assert changes[0].actor == HUMAN
