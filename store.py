import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from company import get_company
from models import (
    CommunicationDraft,
    DetectionGap,
    Incident,
    IncidentEvent,
    IncidentState,
    TriageResult,
    is_human_actor,
    validate_actor,
    validate_intake_actor,
)
from transitions import can_transition

StateLike = Union[IncidentState, str]


class StoreError(Exception):
    pass


_SECRET_FRAGMENTS = ("key", "token", "secret", "password", "authorization")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ms_since(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() * 1000))


def _state_name(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _safe_labels(labels: Optional[dict[str, Any]]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (labels or {}).items():
        lowered = str(key).lower()
        if any(part in lowered for part in _SECRET_FRAGMENTS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe


def _last_state_change_at(incident: Incident) -> datetime:
    for event in reversed(incident.timeline):
        if event.to_state is not None:
            return event.timestamp
    return incident.created_at


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def materialize_from_events(events: list[IncidentEvent]) -> Incident:
    if not events:
        raise StoreError("cannot materialize: no events")
    first = events[0]
    if first.event_type != "incident_created" or first.payload is None:
        raise StoreError("cannot materialize: first event must be incident_created with payload")

    last_state = first.to_state or IncidentState(get_company().start_state)
    last_ts = first.timestamp
    fields: dict[str, Any] = {}
    ai_triage = None
    communications: list[CommunicationDraft] = []
    gaps: dict[str, DetectionGap] = {}
    related = list(first.payload.get("related_incidents") or [])
    for event in events:
        if event.to_state is not None:
            last_state = event.to_state
        last_ts = event.timestamp
        payload = event.payload or {}
        if event.event_type == "ai_triage_proposed" and payload.get("triage"):
            ai_triage = TriageResult.model_validate(payload["triage"])
        elif event.event_type == "triage_applied":
            for key in ("priority", "impact_score", "assigned_to"):
                if payload.get(key) is not None:
                    fields[key] = payload[key]
            if payload.get("duplicate_of"):
                if payload["duplicate_of"] not in related:
                    related.append(payload["duplicate_of"])
        elif event.event_type == "human_override":
            field = payload.get("field")
            if field in {"priority", "impact_score", "assigned_to"}:
                fields[field] = payload.get("value")
        elif event.event_type == "triage_rejected":
            fields.pop("priority", None)
            fields.pop("impact_score", None)
        elif event.event_type == "communication_drafted" and payload.get("draft"):
            communications.append(CommunicationDraft.model_validate(payload["draft"]))
        elif event.event_type == "detection_gaps_proposed":
            for raw in payload.get("gaps") or []:
                gap = DetectionGap.model_validate(raw)
                key = gap.gap_description.strip().lower()
                existing = gaps.get(key)
                if existing is not None and existing.status in {"confirmed", "rejected"}:
                    continue
                if existing is None:
                    gaps[key] = gap
        elif event.event_type == "detection_gap_status":
            key = str(payload.get("key") or "").strip().lower()
            status = payload.get("status")
            if key in gaps and status in {"proposed", "confirmed", "rejected"}:
                gaps[key] = gaps[key].model_copy(update={"status": status})
        elif event.event_type == "assignment_changed":
            fields["assigned_to"] = payload.get("to")
        elif event.event_type == "released":
            fields["assigned_to"] = None
        elif event.event_type == "support_group_changed":
            fields["support_group"] = payload.get("to")

    update = {
        "timeline": list(events),
        "current_state": last_state,
        "updated_at": last_ts,
        "ai_triage": ai_triage,
        "related_incidents": related,
        "communications": communications,
        "detection_gaps": list(gaps.values()),
        **fields,
    }
    return Incident.model_validate(first.payload).model_copy(update=update)


class Store:
    def __init__(self, root: Union[str, Path] = ".") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "incidents.db"
        self.incidents_dir = self.root / "incidents"
        self.incidents_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    current_state TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incident_events (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT,
                    event_json TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(id),
                    UNIQUE (incident_id, seq)
                );

                CREATE TRIGGER IF NOT EXISTS incident_events_no_update
                BEFORE UPDATE ON incident_events
                BEGIN
                    SELECT RAISE(ABORT, 'incident_events is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS incident_events_no_delete
                BEFORE DELETE ON incident_events
                BEGIN
                    SELECT RAISE(ABORT, 'incident_events is append-only');
                END;
                """
            )

    def incident_dir(self, incident_id: str) -> Path:
        return self.incidents_dir / incident_id

    def create_incident(
        self,
        *,
        title: str,
        reporter: str,
        source: str,
        actor: str,
        raw_payload: Optional[dict[str, Any]] = None,
        affected_services: Optional[list[str]] = None,
        affected_ci_ids: Optional[list[str]] = None,
        cmdb_snapshot: Optional[dict[str, Any]] = None,
        support_group: Optional[str] = None,
        incident_id: Optional[str] = None,
    ) -> Incident:
        validate_intake_actor(actor)
        incident_id = incident_id or _new_id("inc")
        if self._exists(incident_id):
            raise StoreError(f"incident already exists: {incident_id}")

        now = _utcnow()
        incident = Incident(
            id=incident_id,
            title=title,
            current_state=IncidentState(get_company().start_state),
            created_at=now,
            updated_at=now,
            reporter=reporter,
            source=source,
            affected_services=list(affected_services or []),
            affected_ci_ids=list(affected_ci_ids or []),
            cmdb_snapshot=dict(cmdb_snapshot or {}),
            support_group=support_group,
        )

        folder = self.incident_dir(incident_id)
        (folder / "raw_inputs").mkdir(parents=True, exist_ok=True)
        (folder / "ai_traces").mkdir(parents=True, exist_ok=True)

        artifacts: list[str] = []
        if raw_payload is not None:
            artifacts.append(self.write_raw_input(incident_id, "intake.json", raw_payload))

        created = IncidentEvent(
            id=_new_id("evt"),
            timestamp=now,
            actor=actor,
            event_type="incident_created",
            from_state=None,
            to_state=IncidentState(get_company().start_state),
            reasoning=f"incident created from {source}",
            artifacts=artifacts,
            payload=incident.model_dump(mode="json"),
        )
        self._insert_incident_and_event(incident, created)
        created_view = self._refresh_snapshot(incident_id)
        elapsed = _ms_since(now, _utcnow())
        return self.emit_metric(created_view.id, "create_latency_ms", elapsed, actor)

    def write_raw_input(self, incident_id: str, name: str, payload: dict[str, Any]) -> str:
        if Path(name).name != name or not name:
            raise StoreError("raw input name must be a basename")
        path = self.incident_dir(incident_id) / "raw_inputs" / name
        if path.exists():
            raise StoreError(f"raw input is immutable: {name} already written")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return f"raw_inputs/{name}"

    def append_event(self, incident_id: str, event: IncidentEvent) -> Incident:
        current = self.materialize(incident_id)
        if event.to_state is not None:
            decision = can_transition(
                current.current_state,
                event.to_state,
                event.actor,
                current.priority,
            )
            if not decision.allowed:
                raise StoreError(decision.reason)
            if event.from_state is not None and event.from_state != current.current_state:
                raise StoreError(
                    f"from_state {event.from_state.value} does not match current {current.current_state.value}"
                )
        self._insert_event(incident_id, event)
        return self._refresh_snapshot(incident_id)

    def transition(
        self,
        incident_id: str,
        to_state: StateLike,
        actor: str,
        reasoning: str,
    ) -> Incident:
        current = self.materialize(incident_id)
        decision = can_transition(current.current_state, to_state, actor, current.priority)
        if not decision.allowed:
            raise StoreError(decision.reason)

        now = _utcnow()
        dwell_ms = _ms_since(_last_state_change_at(current), now)
        target = IncidentState(to_state) if not isinstance(to_state, IncidentState) else to_state
        event = IncidentEvent(
            id=_new_id("evt"),
            timestamp=now,
            actor=actor,
            event_type="state_transition",
            from_state=current.current_state,
            to_state=target,
            reasoning=reasoning,
            requires_approval=decision.requires_human,
            approved_by=actor if decision.requires_human and is_human_actor(actor) else None,
        )
        self._insert_event(incident_id, event)
        left = _state_name(current.current_state)
        self.emit_metric(
            incident_id,
            "state_dwell_ms",
            dwell_ms,
            actor,
            labels={"state": left},
        )
        if _state_name(target) == "TRIAGING":
            self.emit_metric(
                incident_id,
                "time_to_triage_ms",
                _ms_since(current.created_at, now),
                actor,
            )
        return self.materialize(incident_id)

    def emit_metric(
        self,
        incident_id: str,
        name: str,
        value: float,
        actor: str,
        labels: Optional[dict[str, Any]] = None,
    ) -> Incident:
        if not name:
            raise StoreError("metric name required")
        if not isinstance(value, (int, float)):
            raise StoreError("metric value must be numeric")
        payload = {
            "metric": name,
            "value": value,
            "labels": _safe_labels(labels),
        }
        event = IncidentEvent(
            id=_new_id("evt"),
            timestamp=_utcnow(),
            actor=actor,
            event_type="metric",
            reasoning=f"metric {name}={value}",
            payload=payload,
        )
        incident = self.append_event(incident_id, event)
        self._append_metrics_jsonl(incident_id, actor, event.timestamp, payload)
        return incident

    def metric_records(self, incident_id: str) -> list[dict[str, Any]]:
        records = []
        for event in self.get_events(incident_id):
            if event.event_type != "metric" or not event.payload:
                continue
            records.append(
                {
                    "incident_id": incident_id,
                    "metric": event.payload.get("metric"),
                    "value": event.payload.get("value"),
                    "labels": event.payload.get("labels") or {},
                    "timestamp": event.timestamp.isoformat(),
                    "actor": event.actor,
                }
            )
        return records

    def get_events(self, incident_id: str) -> list[IncidentEvent]:
        if not self._exists(incident_id):
            raise StoreError(f"unknown incident: {incident_id}")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_json FROM incident_events WHERE incident_id = ? ORDER BY seq ASC",
                (incident_id,),
            ).fetchall()
        return [IncidentEvent.model_validate_json(row[0]) for row in rows]

    def materialize(self, incident_id: str) -> Incident:
        return materialize_from_events(self.get_events(incident_id))

    def get_incident(self, incident_id: str) -> Incident:
        return self.materialize(incident_id)

    def _exists(self, incident_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return row is not None

    def _next_seq(self, conn: sqlite3.Connection, incident_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM incident_events WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        return int(row[0]) + 1

    def _insert_incident_and_event(self, incident: Incident, event: IncidentEvent) -> None:
        snapshot = incident.model_copy(update={"timeline": [event]})
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO incidents (id, current_state, updated_at, snapshot_json) VALUES (?, ?, ?, ?)",
                (
                    incident.id,
                    incident.current_state.value,
                    incident.updated_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )
            self._insert_event_row(conn, incident.id, event)

    def _insert_event(self, incident_id: str, event: IncidentEvent) -> None:
        with self._connect() as conn:
            self._insert_event_row(conn, incident_id, event)

    def _insert_event_row(self, conn: sqlite3.Connection, incident_id: str, event: IncidentEvent) -> None:
        seq = self._next_seq(conn, incident_id)
        conn.execute(
            """
            INSERT INTO incident_events (
                id, incident_id, seq, timestamp, actor, event_type, from_state, to_state, event_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                incident_id,
                seq,
                event.timestamp.isoformat(),
                event.actor,
                event.event_type,
                event.from_state.value if event.from_state else None,
                event.to_state.value if event.to_state else None,
                event.model_dump_json(),
            ),
        )

    def _refresh_snapshot(self, incident_id: str) -> Incident:
        incident = self.materialize(incident_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE incidents SET current_state = ?, updated_at = ?, snapshot_json = ? WHERE id = ?",
                (
                    incident.current_state.value,
                    incident.updated_at.isoformat(),
                    incident.model_dump_json(),
                    incident_id,
                ),
            )
        folder = self.incident_dir(incident_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "incident.json").write_text(incident.model_dump_json(indent=2), encoding="utf-8")
        return incident

    def _append_metrics_jsonl(
        self,
        incident_id: str,
        actor: str,
        timestamp: datetime,
        payload: dict[str, Any],
    ) -> None:
        runtime = self.root / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        line = {
            "incident_id": incident_id,
            "metric": payload["metric"],
            "value": payload["value"],
            "labels": payload["labels"],
            "timestamp": timestamp.isoformat(),
            "actor": actor,
        }
        with (runtime / "metrics.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")

    def summaries(self, exclude_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, snapshot_json FROM incidents").fetchall()
        out: list[dict[str, Any]] = []
        for incident_id, snapshot in rows:
            if exclude_id and incident_id == exclude_id:
                continue
            data = json.loads(snapshot)
            out.append(
                {
                    "id": incident_id,
                    "title": data.get("title"),
                    "current_state": data.get("current_state"),
                    "affected_ci_ids": data.get("affected_ci_ids") or [],
                    "priority": data.get("priority"),
                }
            )
        return out
