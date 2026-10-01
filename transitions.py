from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from company import Company, get_company
from models import is_human_actor, validate_actor

StateLike = Union[str, Enum]


@dataclass(frozen=True)
class TransitionDecision:
    allowed: bool
    requires_human: bool
    reason: str


def _state_name(value: StateLike) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def can_transition(
    from_state: StateLike,
    to_state: StateLike,
    actor: str,
    priority: Optional[str] = None,
    company: Optional[Company] = None,
) -> TransitionDecision:
    try:
        validate_actor(actor)
    except ValueError as exc:
        return TransitionDecision(allowed=False, requires_human=False, reason=str(exc))

    cfg = company or get_company()
    current = _state_name(from_state)
    target = _state_name(to_state)
    if current not in cfg.states or target not in cfg.states:
        return TransitionDecision(
            allowed=False,
            requires_human=False,
            reason=f"unknown state: {current!r} -> {target!r}",
        )

    rule = cfg.find_transition(current, target)
    if rule is None:
        return TransitionDecision(
            allowed=False,
            requires_human=False,
            reason=f"illegal transition {current} -> {target}",
        )

    requires_human = rule.human_required(priority)
    if requires_human and not is_human_actor(actor):
        return TransitionDecision(
            allowed=False,
            requires_human=True,
            reason=f"{current} -> {target} requires a human actor",
        )

    who = "human" if is_human_actor(actor) else "AI"
    gate = "human-gated" if requires_human else "automatic"
    return TransitionDecision(
        allowed=True,
        requires_human=requires_human,
        reason=f"{current} -> {target} allowed ({gate}, {who})",
    )
