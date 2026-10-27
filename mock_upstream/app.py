"""OpenAI-compatible mock upstream with scriptable failure scenarios."""

import asyncio
import hashlib
import json
import threading
import time
import uuid
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

DEFAULT_USAGE = {"prompt_tokens": 1000, "completion_tokens": 500}
MODELS = ["gpt-5.6-terra", "gpt-5.6-sol"]
STREAM_CHUNKS = 5

Mode = Literal[
    "ok", "error_429", "error_500", "fail_before_stream", "fail_mid_stream", "slow"
]


class ScenarioIn(BaseModel):
    model: str
    mode: Mode
    count: int = 1
    delay_ms: int = 0


class UsageIn(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class MidStreamFailure(Exception):
    """Raised inside the stream generator to drop the connection."""


class MockState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.scenarios: dict[str, dict] = {}
            self.requests: list[dict] = []
            self.usage = dict(DEFAULT_USAGE)

    def record(self, model: str, stream: bool, has_tools: bool, auth: str) -> None:
        entry = {
            "model": model,
            "stream": stream,
            "has_tools": has_tools,
            "ts": time.time(),
            "auth_hash": hashlib.sha256(auth.encode()).hexdigest()[:16],
        }
        with self.lock:
            self.requests.append(entry)

    def next_scenario(self, model: str) -> tuple[str, int]:
        """Consume one use of the model's scenario; fall back to ok."""
        with self.lock:
            sc = self.scenarios.get(model)
            if sc is None:
                return "ok", 0
            sc["count"] -= 1
            mode, delay = sc["mode"], sc["delay_ms"]
            if sc["count"] <= 0:
                del self.scenarios[model]
            return mode, delay

    def get_usage(self) -> dict:
        with self.lock:
            return dict(self.usage)


def _usage_block(usage: dict) -> dict:
    return {**usage, "total_tokens": usage["prompt_tokens"] + usage["completion_tokens"]}


def _error(status: int, err_type: str, code: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"type": err_type, "code": code, "message": "mock"}},
        status_code=status,
    )


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def create_app() -> FastAPI:
    app = FastAPI(title="mock-upstream")
    state = MockState()

    @app.get("/v1/models")
    def list_models() -> dict:
        return {
            "object": "list",
            "data": [
                {"id": m, "object": "model", "created": 0, "owned_by": "mock"}
                for m in MODELS
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        model = body.get("model") or "unknown"
        stream = bool(body.get("stream"))
        tools = body.get("tools") or []
        state.record(model, stream, bool(tools), request.headers.get("authorization", ""))

        mode, delay_ms = state.next_scenario(model)
        if mode == "error_429":
            return _error(429, "rate_limit_error", "rate_limit_exceeded")
        if mode == "error_500":
            return _error(500, "server_error", "server_error")
        if mode == "fail_before_stream":
            return _error(503, "server_error", "service_unavailable")
        if mode == "fail_mid_stream" and not stream:
            return _error(500, "server_error", "server_error")
        if mode == "slow":
            await asyncio.sleep(delay_ms / 1000)

        usage = _usage_block(state.get_usage())
        cid = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        if stream:
            return StreamingResponse(
                _stream(cid, created, model, usage, mode == "fail_mid_stream"),
                media_type="text/event-stream",
            )

        message: dict = {"role": "assistant", "content": "mock-ok"}
        finish = "stop"
        if tools:
            name = (tools[0].get("function") or {}).get("name", "mock_tool")
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_mock_1",
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                ],
            }
            finish = "tool_calls"
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": usage,
        }

    @app.post("/_mock/scenario")
    def set_scenario(sc: ScenarioIn) -> dict:
        with state.lock:
            if sc.mode == "ok":
                state.scenarios.pop(sc.model, None)
            else:
                state.scenarios[sc.model] = {
                    "mode": sc.mode,
                    "count": sc.count,
                    "delay_ms": sc.delay_ms,
                }
        return {"ok": True}

    @app.post("/_mock/usage")
    def set_usage(u: UsageIn) -> dict:
        with state.lock:
            state.usage = u.model_dump()
        return {"ok": True}

    @app.get("/_mock/requests")
    def get_requests() -> list[dict]:
        with state.lock:
            return list(state.requests)

    @app.post("/_mock/reset")
    def reset() -> dict:
        state.reset()
        return {"ok": True}

    return app


async def _stream(cid: str, created: int, model: str, usage: dict, fail_mid: bool):
    for i in range(STREAM_CHUNKS):
        if fail_mid and i == 2:
            raise MidStreamFailure()
        last = i == STREAM_CHUNKS - 1
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": f"mock-{i}"},
                    "finish_reason": "stop" if last else None,
                }
            ],
        }
        if last:
            chunk["usage"] = usage
        yield _sse(chunk)
    yield "data: [DONE]\n\n"


app = create_app()
