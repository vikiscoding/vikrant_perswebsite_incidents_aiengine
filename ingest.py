from typing import Any

from company import IntakeSource, get_company
from cmdb import Cmdb
from models import Incident, validate_intake_actor
from store import Store


class IngestError(Exception):
    pass


def _require_actor(actor: str) -> str:
    return validate_intake_actor(actor)


def _render(template: str, payload: dict[str, Any], source_id: str) -> str:
    try:
        return template.format(**payload)
    except KeyError as exc:
        raise IngestError(f"intake {source_id!r} template missing field {exc}") from exc


def _title(source: IntakeSource, payload: dict[str, Any]) -> str:
    if source.title_template:
        return _render(source.title_template, payload, source.id)
    return str(payload[source.title_field])


def _reporter(source: IntakeSource, payload: dict[str, Any]) -> str:
    if source.reporter_template:
        return _render(source.reporter_template, payload, source.id)
    return str(payload[source.reporter_field])


def ingest(store: Store, source_id: str, payload: dict[str, Any], actor: str, cmdb: Cmdb) -> Incident:
    _require_actor(actor)
    source = get_company().intake_source(source_id)
    if source is None:
        known = [item.id for item in get_company().intake]
        raise IngestError(f"unknown intake source {source_id!r}; configured: {known}")

    missing = [field for field in source.required if payload.get(field) in (None, "")]
    if missing:
        raise IngestError(f"invalid {source_id} payload: missing {missing}")

    service = payload.get(source.service_field) if source.service_field else None
    snapshot = cmdb.snapshot_for(service)
    if snapshot["matched"]:
        services = [snapshot["matched"][0]["name"]]
        ci_ids = list(snapshot.get("affected_ci_ids") or [snapshot["matched"][0]["ci_id"]])
    elif service:
        services = [str(service)]
        ci_ids = []
    else:
        services = []
        ci_ids = []

    return store.create_incident(
        title=_title(source, payload),
        reporter=_reporter(source, payload),
        source=source.id,
        actor=actor,
        raw_payload=payload,
        affected_services=services,
        affected_ci_ids=ci_ids,
        cmdb_snapshot=snapshot,
        support_group=snapshot.get("routing_hint"),
    )


def ingest_alert(store: Store, payload: dict[str, Any], actor: str, cmdb: Cmdb) -> Incident:
    return ingest(store, "alert", payload, actor, cmdb)


def ingest_manual(store: Store, payload: dict[str, Any], actor: str, cmdb: Cmdb) -> Incident:
    return ingest(store, "manual", payload, actor, cmdb)
