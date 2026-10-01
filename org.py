"""Compatibility facade. Edit company.toml — do not hardcode a new org here."""

from company import get_company


def __getattr__(name: str):
    cfg = get_company()
    mapping = {
        "COMPANY": cfg.name,
        "COMPANY_KIND": cfg.kind,
        "TEAMS": cfg.team_map(),
        "OWNING_TEAMS": cfg.owning_teams(),
    }
    if name in mapping:
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
