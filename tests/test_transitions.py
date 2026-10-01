import pytest

from models import IncidentState
from transitions import can_transition


AI = "ai:grok:grok-4"
HUMAN = "human:vikrant"


def test_happy_path_detected_to_closed():
    assert can_transition(IncidentState.DETECTED, IncidentState.TRIAGING, AI).allowed
    assert can_transition(IncidentState.TRIAGING, IncidentState.ACKNOWLEDGED, AI, priority="Low").allowed
    assert can_transition(IncidentState.ACKNOWLEDGED, IncidentState.ACTIVE, AI).allowed
    resolve = can_transition(IncidentState.ACTIVE, IncidentState.RESOLVED, HUMAN)
    assert resolve.allowed and resolve.requires_human
    close = can_transition(IncidentState.RESOLVED, IncidentState.CLOSED, HUMAN)
    assert close.allowed and close.requires_human


@pytest.mark.parametrize(
    "frm, to",
    [
        (IncidentState.DETECTED, IncidentState.ACKNOWLEDGED),
        (IncidentState.DETECTED, IncidentState.ACTIVE),
        (IncidentState.DETECTED, IncidentState.RESOLVED),
        (IncidentState.DETECTED, IncidentState.CLOSED),
        (IncidentState.TRIAGING, IncidentState.ACTIVE),
        (IncidentState.TRIAGING, IncidentState.RESOLVED),
        (IncidentState.TRIAGING, IncidentState.CLOSED),
        (IncidentState.ACKNOWLEDGED, IncidentState.RESOLVED),
        (IncidentState.ACKNOWLEDGED, IncidentState.CLOSED),
        (IncidentState.ACKNOWLEDGED, IncidentState.DETECTED),
        (IncidentState.ACTIVE, IncidentState.CLOSED),
        (IncidentState.ACTIVE, IncidentState.DETECTED),
        (IncidentState.RESOLVED, IncidentState.TRIAGING),
        (IncidentState.CLOSED, IncidentState.DETECTED),
        (IncidentState.CLOSED, IncidentState.CLOSED),
        (IncidentState.DETECTED, IncidentState.DETECTED),
    ],
)
def test_illegal_jumps_rejected(frm, to):
    decision = can_transition(frm, to, HUMAN)
    assert decision.allowed is False
    assert decision.requires_human is False
    assert "illegal" in decision.reason


@pytest.mark.parametrize("priority", ["High", "Critical"])
def test_high_critical_ack_rejects_ai_accepts_human(priority):
    ai = can_transition(IncidentState.TRIAGING, IncidentState.ACKNOWLEDGED, AI, priority=priority)
    human = can_transition(IncidentState.TRIAGING, IncidentState.ACKNOWLEDGED, HUMAN, priority=priority)
    assert ai.allowed is False
    assert ai.requires_human is True
    assert human.allowed is True
    assert human.requires_human is True


@pytest.mark.parametrize("priority", ["Low", "Medium"])
def test_low_medium_ack_allows_ai(priority):
    decision = can_transition(IncidentState.TRIAGING, IncidentState.ACKNOWLEDGED, AI, priority=priority)
    assert decision.allowed is True
    assert decision.requires_human is False


def test_missing_priority_on_ack_fails_closed():
    ai = can_transition(IncidentState.TRIAGING, IncidentState.ACKNOWLEDGED, AI)
    human = can_transition(IncidentState.TRIAGING, IncidentState.ACKNOWLEDGED, HUMAN)
    assert ai.allowed is False
    assert ai.requires_human is True
    assert human.allowed is True
    assert human.requires_human is True


@pytest.mark.parametrize(
    "frm, to",
    [
        (IncidentState.ACTIVE, IncidentState.RESOLVED),
        (IncidentState.RESOLVED, IncidentState.CLOSED),
        (IncidentState.RESOLVED, IncidentState.ACTIVE),
        (IncidentState.CLOSED, IncidentState.ACTIVE),
    ],
)
def test_resolve_close_reopen_reject_ai_accept_human(frm, to):
    ai = can_transition(frm, to, AI)
    human = can_transition(frm, to, HUMAN)
    assert ai.allowed is False
    assert ai.requires_human is True
    assert human.allowed is True
    assert human.requires_human is True


@pytest.mark.parametrize("actor", ["", "system", "admin", "ai:grok:", "human:", "nobody"])
def test_invalid_actor_rejected(actor):
    decision = can_transition(IncidentState.DETECTED, IncidentState.TRIAGING, actor)
    assert decision.allowed is False
    assert decision.requires_human is False


def test_acknowledged_to_active_is_automatic():
    decision = can_transition(IncidentState.ACKNOWLEDGED, IncidentState.ACTIVE, AI)
    assert decision.allowed is True
    assert decision.requires_human is False


def test_accepts_string_states():
    decision = can_transition("DETECTED", "TRIAGING", AI)
    assert decision.allowed is True
