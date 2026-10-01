import json
import os

import httpx
import pytest
from pydantic import BaseModel, Field

from grok import GrokClient
from models import IncidentState
from store import Store

HUMAN = "human:vikrant"


class Ping(BaseModel):
    ok: bool
    confidence: float = Field(ge=0, le=1)


def _incident(store: Store):
    return store.create_incident(
        title="website 5xx",
        reporter="alert:web",
        source="alert",
        actor=HUMAN,
    )


def _client(store: Store, handler) -> GrokClient:
    transport = httpx.MockTransport(handler)
    return GrokClient(
        store,
        client=httpx.Client(transport=transport),
        api_key="test-key",
        model="grok-4.5",
    )


def test_structured_success_writes_trace_and_metrics(tmp_path):
    store = Store(tmp_path)
    incident = _incident(store)
    state_before = incident.current_state

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"ok": True, "confidence": 0.91})}}]},
        )

    grok = _client(store, handler)
    result = grok.complete_structured(
        "ping",
        Ping,
        incident_id=incident.id,
        purpose="slice5-smoke",
    )
    assert result.ok is True
    assert result.parsed == {"ok": True, "confidence": 0.91}
    assert result.confidence == 0.91
    trace = tmp_path / "incidents" / incident.id / result.trace_path
    saved = json.loads(trace.read_text(encoding="utf-8"))
    assert saved["parsed_ok"] is True
    assert saved["purpose"] == "slice5-smoke"
    assert saved["model"] == "grok-4.5"
    assert "test-key" not in trace.read_text(encoding="utf-8")
    metrics = {row["metric"]: row["value"] for row in store.metric_records(incident.id)}
    assert metrics["ai_call_error"] == 0
    assert "ai_call_latency_ms" in metrics
    loaded = store.get_incident(incident.id)
    assert loaded.current_state is state_before
    assert any(event.event_type == "ai_call" for event in loaded.timeline)


def test_http_error_fails_soft_and_still_traces(tmp_path):
    store = Store(tmp_path)
    incident = _incident(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom Bearer sk-live")

    result = _client(store, handler).complete_structured(
        "ping",
        Ping,
        incident_id=incident.id,
        purpose="http-fail",
    )
    assert result.ok is False
    assert result.parsed is None
    assert "500" in (result.error or "")
    assert "sk-live" not in (result.error or "")
    trace = json.loads((tmp_path / "incidents" / incident.id / result.trace_path).read_text(encoding="utf-8"))
    assert trace["parsed_ok"] is False
    assert store.get_incident(incident.id).current_state is IncidentState.DETECTED
    assert store.metric_records(incident.id)[-1]["metric"] == "ai_call_error"
    assert store.metric_records(incident.id)[-1]["value"] == 1


def test_schema_failure_is_not_a_silent_default(tmp_path):
    store = Store(tmp_path)
    incident = _incident(store)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"ok": True, "confidence": 9})}}]},
        )

    result = _client(store, handler).complete_structured(
        "ping",
        Ping,
        incident_id=incident.id,
        purpose="bad-schema",
    )
    assert result.ok is False
    assert result.parsed is None
    assert "schema validation failed" in (result.error or "")


def test_missing_confidence_rejected(tmp_path):
    store = Store(tmp_path)
    incident = _incident(store)

    class NoConfidence(BaseModel):
        label: str

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"label": "x"})}}]},
        )

    result = _client(store, handler).complete_structured(
        "x",
        NoConfidence,
        incident_id=incident.id,
        purpose="no-confidence",
    )
    assert result.ok is False
    assert result.parsed is None
    assert "confidence" in (result.error or "")


def test_missing_api_key_fails_soft_with_trace(tmp_path):
    store = Store(tmp_path)
    incident = _incident(store)
    grok = GrokClient(store, client=httpx.Client(), api_key="", model="grok-4.5")
    result = grok.complete_structured("ping", Ping, incident_id=incident.id, purpose="no-key")
    assert result.ok is False
    assert "XAI_API_KEY" in (result.error or "")
    assert (tmp_path / "incidents" / incident.id / result.trace_path).is_file()


def test_progress_line_says_not_available_when_dead(tmp_path, capsys):
    store = Store(tmp_path)
    incident = _incident(store)
    grok = GrokClient(store, client=httpx.Client(), api_key="", model="grok-4.5", progress=True)
    result = grok.complete_structured("ping", Ping, incident_id=incident.id, purpose="no-key")
    err = capsys.readouterr().err
    assert result.ok is False
    assert "grok not available" in err
    assert "not configured" in err


@pytest.mark.skipif(not os.environ.get("XAI_API_KEY"), reason="live xAI smoke requires XAI_API_KEY")
def test_live_smoke_writes_trace(tmp_path):
    store = Store(tmp_path)
    incident = _incident(store)
    grok = GrokClient(store)
    result = grok.complete_structured(
        'Reply with ok=true and a confidence between 0 and 1.',
        Ping,
        incident_id=incident.id,
        purpose="live-smoke",
    )
    grok.close()
    assert result.trace_path
    assert (tmp_path / "incidents" / incident.id / result.trace_path).is_file()
