"""site_bridge.py end to end on a temp store, model down (no XAI_API_KEY): the ticket survives and a human finishes."""

import json

import pytest

import site_bridge as bridge
from store import Store

ALERT = json.dumps({"monitor": "vikrantsingh.fyi heartbeat", "service": "vikrantsingh.fyi", "message": "ticker failed twice: http 503"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    root = tmp_path / "data"

    def run(*argv, **envs):
        out.write_text("", encoding="utf-8")
        for k, v in envs.items():
            monkeypatch.setenv(k, v)
        assert bridge.main(["--root", str(root), *argv]) == 0
        values, key, buf = {}, None, []
        for line in out.read_text(encoding="utf-8").splitlines():
            if key is None and "<<__EOF__" in line:
                key, buf = line.split("<<")[0], []
            elif line == "__EOF__":
                values[key], key = "\n".join(buf), None
            else:
                buf.append(line)
        return values

    return root, run


def test_full_lifecycle_model_down(env):
    root, run = env
    first = run("alert", ALERT_PAYLOAD=ALERT)
    assert first["mode"] == "new" and first["title"].startswith("[inc-")
    assert "service:vikrantsingh.fyi-heartbeat" in first["body"] and "/resolve" in first["body"]
    inc = first["incident_id"]

    assert run("alert", ALERT_PAYLOAD=ALERT)["mode"] == "duplicate"  # same open incident, no new ticket
    run("link", "--incident", inc, "--issue", "7")

    assert "only the repo owner" in run("command", "--issue", "7", "--author", "someone", COMMENT_BODY="/close")["reply"]
    assert "needs a reason" in run("command", "--issue", "7", "--author", "vikiscoding", COMMENT_BODY="/resolve")["reply"]

    ack = run("command", "--issue", "7", "--author", "vikiscoding", COMMENT_BODY="/ack")
    assert "State now **ACTIVE**" in ack["reply"], ack["reply"]
    run("command", "--issue", "7", "--author", "vikiscoding", COMMENT_BODY="/note checked GitHub status page")

    rec = run("recovered", ALERT_PAYLOAD=json.dumps({"monitor": "vikrantsingh.fyi heartbeat", "service": "vikrantsingh.fyi", "message": "ticker healthy"}))
    assert rec["mode"] == "recovered" and "human decision" in rec["reply"]

    assert "RESOLVED" in run("command", "--issue", "7", "--author", "vikiscoding", COMMENT_BODY="/resolve GitHub API recovered")["reply"]
    closed = run("command", "--issue", "7", "--author", "vikiscoding", COMMENT_BODY="/close")
    assert closed["close"] == "true"

    run("feed", GITHUB_REPOSITORY="vikiscoding/test")
    feed = json.loads((root / "feed.json").read_text(encoding="utf-8"))
    item = feed["incidents"][0]
    assert item["state"] == "CLOSED" and item["issue_url"].endswith("/issues/7") and item["recovered_at"]
    kinds = {e["kind"] for e in item["timeline"]}
    assert {"service", "human"} <= kinds
    assert item["note"] == "checked GitHub status page"  # the owner's latest /note reaches the site
    actors = [e.actor for e in Store(root).get_incident(inc).timeline if e.event_type == "state_changed" or e.to_state]
    assert all(not a.startswith("service:") for a in actors[1:])  # the service only created it


def test_refusal_says_what_is_next_and_ack_is_state_aware(env):
    root, run = env
    inc = run("alert", ALERT_PAYLOAD=ALERT)["incident_id"]
    run("link", "--incident", inc, "--issue", "9")
    early = run("command", "--issue", "9", "--author", "vikiscoding", COMMENT_BODY="/resolve test is finished")["reply"]
    assert "refused" in early and "Next: `/ack`" in early  # game day 1: TRIAGING -> RESOLVED is illegal
    assert "State now **ACTIVE**" in run("command", "--issue", "9", "--author", "vikiscoding", COMMENT_BODY="/ack")["reply"]
    assert "Nothing to acknowledge" in run("command", "--issue", "9", "--author", "vikiscoding", COMMENT_BODY="/ack")["reply"]


def test_guard_reopens_an_issue_closed_by_hand(env):
    root, run = env
    inc = run("alert", ALERT_PAYLOAD=ALERT)["incident_id"]
    run("link", "--incident", inc, "--issue", "4")
    g = run("guard", "--issue", "4")
    assert g["reopen"] == "true" and "does not close the incident" in g["reply"]
    for cmd in ("/ack", "/resolve done", "/close"):
        run("command", "--issue", "4", "--author", "vikiscoding", COMMENT_BODY=cmd)
    assert run("guard", "--issue", "4")["reopen"] == "false"


def test_open_manual_test_never_swallows_a_real_alert(env):
    root, run = env
    manual = json.dumps({"monitor": "manual test", "service": "vikrantsingh.fyi", "message": "key test"})
    assert run("alert", ALERT_PAYLOAD=manual)["mode"] == "new"
    assert run("alert", ALERT_PAYLOAD=ALERT)["mode"] == "new"  # different monitor: its own incident
    assert run("alert", ALERT_PAYLOAD=ALERT)["mode"] == "duplicate"  # same monitor again: deduped


def test_leading_whitespace_and_plain_comments(env):
    root, run = env
    inc = run("alert", ALERT_PAYLOAD=ALERT)["incident_id"]
    run("link", "--incident", inc, "--issue", "5")
    assert "State now **ACTIVE**" in run("command", "--issue", "5", "--author", "vikiscoding", COMMENT_BODY=" /ack")["reply"]
    quiet = run("command", "--issue", "5", "--author", "vikiscoding", COMMENT_BODY="see https://githubstatus.com for details")
    assert quiet["reply"] == "" and quiet["close"] == "false"


def test_unknown_command_returns_help(env):
    root, run = env
    inc = run("alert", ALERT_PAYLOAD=ALERT)["incident_id"]
    run("link", "--incident", inc, "--issue", "3")
    assert "/approve" in run("command", "--issue", "3", "--author", "vikiscoding", COMMENT_BODY="/dance")["reply"]


@pytest.mark.parametrize("bad", ["[]", "{}", '{"monitor":"x"}', "x" * 5000])
def test_bad_alert_payload_rejected(bad):
    with pytest.raises(ValueError):
        bridge.parse_alert(bad)


def test_gate_label_marks_pre_policy_auto_apply_as_history():
    """A pre-ADR-021 auto-apply reads as history; one after the rule would be shown as a breach, never as normal."""
    from datetime import timedelta
    from types import SimpleNamespace

    def inc(at):
        return SimpleNamespace(timeline=[SimpleNamespace(event_type="triage_applied", approved_by=None, timestamp=at)])

    before = bridge.gate_label(inc(bridge.NO_AUTO_APPLY_SINCE - timedelta(hours=12)))
    after = bridge.gate_label(inc(bridge.NO_AUTO_APPLY_SINCE + timedelta(minutes=1)))
    assert "earlier low-risk rule" in before and "now waits for /approve" in before
    assert "against the live-desk rule" in after
