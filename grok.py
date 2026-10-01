import json
import os
import re
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from models import IncidentEvent
from store import Store, StoreError, _utcnow

DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.5"
T = TypeVar("T", bound=BaseModel)
_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


class StructuredResult(BaseModel):
    ok: bool
    parsed: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    trace_id: str
    latency_ms: int
    confidence: Optional[float] = None
    model: str
    trace_path: Optional[str] = None


def _redact(text: str) -> str:
    return _BEARER.sub("Bearer [redacted]", text)


def _settings() -> tuple[str, str, str]:
    key = os.environ.get("XAI_API_KEY") or ""
    base = (os.environ.get("XAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("XAI_MODEL") or DEFAULT_MODEL
    return key, base, model


def _confidence(parsed: BaseModel) -> Optional[float]:
    value = getattr(parsed, "confidence", None)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _stderr_is_tty() -> bool:
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


@contextmanager
def _wait_flash(message: str, enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    stop = threading.Event()
    frames = "|/-\\"

    def spin() -> None:
        i = 0
        while not stop.wait(0.12):
            sys.stderr.write(f"\r{frames[i % 4]} {message}   ")
            sys.stderr.flush()
            i += 1

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
        sys.stderr.write("\r" + " " * (len(message) + 8) + "\r")
        sys.stderr.flush()


def _announce(ok: bool, error: Optional[str], enabled: bool) -> None:
    if not enabled:
        return
    if ok:
        sys.stderr.write("grok replied.\n")
    else:
        why = error or "no response"
        if "XAI_API_KEY" in why:
            why = "not configured (no XAI_API_KEY)"
        elif "ConnectError" in why or "timed out" in why.lower() or "Timeout" in why:
            why = "unreachable or timed out"
        elif "HTTP 5" in why:
            why = "server error (dead or overloaded)"
        elif "HTTP 401" in why or "HTTP 403" in why:
            why = "refused (auth)"
        sys.stderr.write(f"grok not available — {why}\n")
    sys.stderr.flush()


class GrokClient:
    def __init__(
        self,
        store: Store,
        *,
        client: Optional[httpx.Client] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        progress: Optional[bool] = None,
    ) -> None:
        env_key, env_base, env_model = _settings()
        self.store = store
        self.api_key = env_key if api_key is None else api_key
        self.base_url = (env_base if base_url is None else base_url).rstrip("/")
        self.model = env_model if model is None else model
        self._owns_client = client is None
        self._http = client or httpx.Client(timeout=60.0)
        self.progress = _stderr_is_tty() if progress is None else progress

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def complete_structured(
        self,
        prompt: str,
        schema: Type[T],
        *,
        incident_id: str,
        purpose: str,
        system: str = "Return only JSON that matches the provided schema. Do not invent fields.",
    ) -> StructuredResult:
        trace_id = f"trc-{uuid.uuid4().hex[:12]}"
        started = datetime.now(timezone.utc)
        raw_response: Optional[str] = None
        parsed_model: Optional[BaseModel] = None
        error: Optional[str] = None

        try:
            with _wait_flash(f"waiting on grok ({purpose})", self.progress):
                raw_response, parsed_model = self._call(prompt, schema, system)
        except Exception as exc:
            error = _redact(str(exc))

        ended = datetime.now(timezone.utc)
        latency_ms = max(0, int((ended - started).total_seconds() * 1000))
        parsed_ok = parsed_model is not None and error is None
        confidence = _confidence(parsed_model) if parsed_model is not None else None
        if parsed_ok and confidence is None:
            error = "structured output missing required confidence"
            parsed_ok = False
            parsed_model = None

        result = StructuredResult(
            ok=parsed_ok,
            parsed=parsed_model.model_dump(mode="json") if parsed_ok and parsed_model else None,
            error=error,
            trace_id=trace_id,
            latency_ms=latency_ms,
            confidence=confidence if parsed_ok else None,
            model=self.model,
        )
        result.trace_path = self._write_trace(
            incident_id=incident_id,
            purpose=purpose,
            trace_id=trace_id,
            started=started,
            ended=ended,
            latency_ms=latency_ms,
            prompt=prompt,
            raw_response=raw_response,
            parsed_ok=parsed_ok,
            parsed_output=result.parsed,
            error=error,
            confidence=result.confidence,
        )
        self._record(incident_id, purpose, result)
        _announce(result.ok, result.error, self.progress)
        return result

    def _call(self, prompt: str, schema: Type[T], system: str) -> tuple[str, T]:
        if not self.api_key:
            raise RuntimeError("XAI_API_KEY is not set")
        json_schema = schema.model_json_schema()
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": True,
                },
            },
        }
        response = self._http.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        raw_text = _redact(response.text)
        if response.status_code >= 400:
            raise RuntimeError(f"xAI HTTP {response.status_code}: {raw_text[:500]}")
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not content:
            raise RuntimeError("xAI returned empty content")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"xAI returned non-JSON content: {exc}") from exc
        try:
            return content, schema.model_validate(data)
        except ValidationError as exc:
            raise RuntimeError(f"schema validation failed: {exc}") from exc

    def _write_trace(
        self,
        *,
        incident_id: str,
        purpose: str,
        trace_id: str,
        started: datetime,
        ended: datetime,
        latency_ms: int,
        prompt: str,
        raw_response: Optional[str],
        parsed_ok: bool,
        parsed_output: Optional[dict[str, Any]],
        error: Optional[str],
        confidence: Optional[float],
    ) -> str:
        folder = self.store.incident_dir(incident_id) / "ai_traces"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{trace_id}.json"
        path.write_text(
            json.dumps(
                {
                    "trace_id": trace_id,
                    "incident_id": incident_id,
                    "purpose": purpose,
                    "model": self.model,
                    "started_at": started.isoformat(),
                    "ended_at": ended.isoformat(),
                    "latency_ms": latency_ms,
                    "prompt": prompt,
                    "raw_response": raw_response,
                    "parsed_ok": parsed_ok,
                    "parsed_output": parsed_output,
                    "error": error,
                    "confidence": confidence,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return f"ai_traces/{trace_id}.json"

    def _record(self, incident_id: str, purpose: str, result: StructuredResult) -> None:
        actor = f"ai:grok:{self.model}"
        try:
            self.store.emit_metric(
                incident_id,
                "ai_call_latency_ms",
                result.latency_ms,
                actor,
                labels={"purpose": purpose},
            )
            self.store.emit_metric(
                incident_id,
                "ai_call_error",
                0 if result.ok else 1,
                actor,
                labels={"purpose": purpose},
            )
            self.store.append_event(
                incident_id,
                IncidentEvent(
                    id=f"evt-{uuid.uuid4().hex[:12]}",
                    timestamp=_utcnow(),
                    actor=actor,
                    event_type="ai_call",
                    reasoning=purpose,
                    confidence=result.confidence,
                    artifacts=[result.trace_path] if result.trace_path else [],
                    payload={"parsed_ok": result.ok, "error": result.error, "trace_id": result.trace_id},
                ),
            )
        except StoreError:
            return
