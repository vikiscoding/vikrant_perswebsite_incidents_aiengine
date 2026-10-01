import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from company import get_company


class ConfigurationItem(BaseModel):
    ci_id: str
    name: str
    type: str
    environment: str
    status: str
    criticality: str
    owner_team: str
    technical_contact: str
    depends_on: list[str]
    details: Optional[dict] = Field(default=None)

    @field_validator("owner_team")
    @classmethod
    def _known_team(cls, value: str) -> str:
        allowed = get_company().owning_teams()
        if value not in allowed:
            raise ValueError(f"owner_team must be one of {sorted(allowed)}")
        return value


class Cmdb:
    def __init__(self, items: list[ConfigurationItem]) -> None:
        self.items = items
        self._by_id = {item.ci_id: item for item in items}
        self._by_name = {item.name.lower(): item for item in items}

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Cmdb":
        path = path or get_company().cmdb_path
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls([ConfigurationItem(**row) for row in raw])

    def find(self, service: str) -> Optional[ConfigurationItem]:
        if not service:
            return None
        found = self._by_id.get(service)
        if found:
            return found
        return self._by_name.get(service.lower())

    def used_by(self, ci_id: str) -> list[ConfigurationItem]:
        return [item for item in self.items if ci_id in item.depends_on]

    def _walk_depends(self, start: ConfigurationItem, max_hops: int = 2) -> list[tuple[int, ConfigurationItem]]:
        seen = {start.ci_id}
        found: list[tuple[int, ConfigurationItem]] = []
        frontier: list[tuple[int, str]] = [(1, dep_id) for dep_id in start.depends_on]
        while frontier:
            hop, dep_id = frontier.pop(0)
            if dep_id in seen or dep_id not in self._by_id:
                continue
            seen.add(dep_id)
            item = self._by_id[dep_id]
            found.append((hop, item))
            if hop < max_hops:
                for next_id in item.depends_on:
                    frontier.append((hop + 1, next_id))
        return found

    def snapshot_for(self, service: Optional[str]) -> dict:
        empty = {
            "primary_ci_id": None,
            "matched": [],
            "dependencies": [],
            "dependencies_indirect": [],
            "used_by": [],
            "affected_ci_ids": [],
            "routing_hint": None,
        }
        if not service:
            return empty
        match = self.find(service)
        if match is None:
            return {**empty, "unknown_service": service}

        walked = self._walk_depends(match, max_hops=2)
        direct = [item.model_dump() for hop, item in walked if hop == 1]
        indirect = [item.model_dump() for hop, item in walked if hop > 1]
        dependents = [item.model_dump() for item in self.used_by(match.ci_id)]

        affected: list[str] = [match.ci_id]
        for hop, item in walked:
            if item.ci_id not in affected:
                affected.append(item.ci_id)
        for item in self.used_by(match.ci_id):
            if item.ci_id not in affected:
                affected.append(item.ci_id)

        return {
            "primary_ci_id": match.ci_id,
            "matched": [match.model_dump()],
            "dependencies": direct,
            "dependencies_indirect": indirect,
            "used_by": dependents,
            "affected_ci_ids": affected,
            "routing_hint": match.owner_team,
        }
