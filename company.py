from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_COMPANY_FILE = Path(__file__).resolve().parent / "company.toml"
ENV_COMPANY_FILE = "INCIDENT_COMPANY_FILE"
HUMAN_RULES = ("never", "always", "if_high_or_unknown_priority")
AUTO_APPLY_PRIORITIES = frozenset({"Low", "Medium"})

_CACHE: Optional["Company"] = None


class CompanyConfigError(Exception):
    pass


@dataclass(frozen=True)
class Team:
    name: str
    description: str


@dataclass(frozen=True)
class TransitionRule:
    from_state: str
    to_state: str
    requires_human: str

    def human_required(self, priority: Optional[str]) -> bool:
        if self.requires_human == "always":
            return True
        if self.requires_human == "never":
            return False
        return priority not in AUTO_APPLY_PRIORITIES


@dataclass(frozen=True)
class IntakeSource:
    id: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    service_field: Optional[str]
    title_template: Optional[str]
    title_field: Optional[str]
    reporter_template: Optional[str]
    reporter_field: Optional[str]
    untrusted_priority_fields: tuple[str, ...]


@dataclass(frozen=True)
class Company:
    name: str
    kind: str
    description: str
    cmdb_path: Path
    teams: tuple[Team, ...]
    states: tuple[str, ...]
    start_state: str
    transitions: tuple[TransitionRule, ...]
    intake: tuple[IntakeSource, ...]

    def owning_teams(self) -> frozenset[str]:
        return frozenset(team.name for team in self.teams)

    def team_map(self) -> dict[str, str]:
        return {team.name: team.description for team in self.teams}

    def find_transition(self, from_state: str, to_state: str) -> Optional[TransitionRule]:
        for rule in self.transitions:
            if rule.from_state == from_state and rule.to_state == to_state:
                return rule
        return None

    def intake_source(self, source_id: str) -> Optional[IntakeSource]:
        for source in self.intake:
            if source.id == source_id:
                return source
        return None


def company_file() -> Path:
    override = os.environ.get(ENV_COMPANY_FILE)
    return Path(override) if override else DEFAULT_COMPANY_FILE


def reset_company() -> None:
    global _CACHE
    _CACHE = None


def get_company() -> Company:
    global _CACHE
    if _CACHE is None:
        _CACHE = load_company(company_file())
    return _CACHE


def load_company(path: Path) -> Company:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CompanyConfigError(f"company file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CompanyConfigError(f"invalid company TOML: {exc}") from exc

    meta = raw.get("company") or {}
    for key in ("name", "kind"):
        if not meta.get(key):
            raise CompanyConfigError(f"company.{key} is required")

    teams_raw = raw.get("teams") or []
    if not teams_raw:
        raise CompanyConfigError("at least one [[teams]] entry is required")
    teams = tuple(Team(name=str(row["name"]), description=str(row.get("description") or "")) for row in teams_raw)
    names = [team.name for team in teams]
    if len(names) != len(set(names)):
        raise CompanyConfigError("team names must be unique")

    life = raw.get("lifecycle") or {}
    states = tuple(str(state) for state in (life.get("states") or []))
    if not states:
        raise CompanyConfigError("lifecycle.states is required")
    start_state = str(life.get("start_state") or states[0])
    if start_state not in states:
        raise CompanyConfigError(f"start_state {start_state!r} is not in lifecycle.states")

    rules: list[TransitionRule] = []
    for row in life.get("transitions") or []:
        rule = TransitionRule(
            from_state=str(row["from"]),
            to_state=str(row["to"]),
            requires_human=str(row.get("requires_human") or "always"),
        )
        if rule.requires_human not in HUMAN_RULES:
            raise CompanyConfigError(
                f"requires_human must be one of {HUMAN_RULES}, got {rule.requires_human!r}"
            )
        if rule.from_state not in states or rule.to_state not in states:
            raise CompanyConfigError(
                f"transition {rule.from_state} -> {rule.to_state} references an unknown state"
            )
        rules.append(rule)
    if not rules:
        raise CompanyConfigError("lifecycle.transitions is required")

    sources: list[IntakeSource] = []
    for row in raw.get("intake") or []:
        source = IntakeSource(
            id=str(row["id"]),
            required=tuple(row.get("required") or []),
            optional=tuple(row.get("optional") or []),
            service_field=row.get("service_field"),
            title_template=row.get("title_template"),
            title_field=row.get("title_field"),
            reporter_template=row.get("reporter_template"),
            reporter_field=row.get("reporter_field"),
            untrusted_priority_fields=tuple(row.get("untrusted_priority_fields") or []),
        )
        if not source.title_template and not source.title_field:
            raise CompanyConfigError(f"intake {source.id!r} needs title_template or title_field")
        if not source.reporter_template and not source.reporter_field:
            raise CompanyConfigError(f"intake {source.id!r} needs reporter_template or reporter_field")
        sources.append(source)
    if not sources:
        raise CompanyConfigError("at least one [[intake]] source is required")
    if len({source.id for source in sources}) != len(sources):
        raise CompanyConfigError("intake ids must be unique")

    cmdb = meta.get("cmdb") or "mock_cmdb.json"
    cmdb_path = Path(cmdb)
    if not cmdb_path.is_absolute():
        cmdb_path = path.parent / cmdb_path

    return Company(
        name=str(meta["name"]),
        kind=str(meta["kind"]),
        description=str(meta.get("description") or ""),
        cmdb_path=cmdb_path,
        teams=teams,
        states=states,
        start_state=start_state,
        transitions=tuple(rules),
        intake=tuple(sources),
    )
