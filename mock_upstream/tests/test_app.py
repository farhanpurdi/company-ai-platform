import json

import pytest
from fastapi.testclient import TestClient

from app import create_app

TERRA = "gpt-5.6-terra"
SOL = "gpt-5.6-sol"
BODY = {"model": TERRA, "messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture()
def client():
    return TestClient(create_app())


def sse_data(lines):
    return [ln[len("data: "):] for ln in lines if ln.startswith("data: ")]


def test_ok_nonstream_usage_and_model(client):
    r = client.post("/v1/chat/completions", json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == TERRA
    assert data["choices"][0]["message"]["content"] == "mock-ok"
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"]["prompt_tokens"] == 1000
    assert data["usage"]["completion_tokens"] == 500

    client.post("/_mock/usage", json={"prompt_tokens": 7, "completion_tokens": 3})
    data = client.post("/v1/chat/completions", json=BODY).json()
    assert data["usage"]["prompt_tokens"] == 7
    assert data["usage"]["completion_tokens"] == 3

    models = client.get("/v1/models").json()["data"]
    assert [m["id"] for m in models] == [TERRA, SOL]


def test_usage_itemizes_cached_prompt_tokens_like_openai(client):
    assert "prompt_tokens_details" not in client.post("/v1/chat/completions", json=BODY).json()["usage"]
    client.post("/_mock/usage", json={"prompt_tokens": 1000, "completion_tokens": 500, "cached_tokens": 800})
    usage = client.post("/v1/chat/completions", json=BODY).json()["usage"]
    # OpenAI counts cached tokens inside prompt_tokens.
    assert usage["prompt_tokens"] == 1000
    assert usage["prompt_tokens_details"] == {"cached_tokens": 800}


def test_stream_yields_5_chunks_then_usage_then_done(client):
    with client.stream("POST", "/v1/chat/completions", json={**BODY, "stream": True}) as r:
        assert r.status_code == 200
        payloads = sse_data(list(r.iter_lines()))
    assert payloads[-1] == "[DONE]"
    chunks = [json.loads(p) for p in payloads[:-1]]
    assert len(chunks) == 5
    assert [c["choices"][0]["delta"]["content"] for c in chunks] == [f"mock-{i}" for i in range(5)]
    assert all("usage" not in c for c in chunks[:-1])
    assert chunks[-1]["usage"]["prompt_tokens"] == 1000
    assert chunks[-1]["usage"]["completion_tokens"] == 500


def test_tools_returns_tool_call_named_after_first_tool(client):
    tools = [
        {"type": "function", "function": {"name": "get_weather", "parameters": {}}},
        {"type": "function", "function": {"name": "other", "parameters": {}}},
    ]
    data = client.post("/v1/chat/completions", json={**BODY, "tools": tools}).json()
    choice = data["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"] == [
        {
            "id": "call_mock_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": "{}"},
        }
    ]


def test_scenario_error_429_applies_count_times_then_ok(client):
    client.post("/_mock/scenario", json={"model": TERRA, "mode": "error_429", "count": 2})
    first = client.post("/v1/chat/completions", json=BODY)
    assert first.status_code == 429
    assert first.json() == {
        "error": {"type": "rate_limit_error", "code": "rate_limit_exceeded", "message": "mock"}
    }
    assert client.post("/v1/chat/completions", json=BODY).status_code == 429
    assert client.post("/v1/chat/completions", json=BODY).status_code == 200
    # failed requests are recorded too
    assert len(client.get("/_mock/requests").json()) == 3


def test_scenario_is_per_model(client):
    client.post("/_mock/scenario", json={"model": SOL, "mode": "error_500", "count": 1})
    assert client.post("/v1/chat/completions", json=BODY).status_code == 200
    r = client.post("/v1/chat/completions", json={**BODY, "model": SOL})
    assert r.status_code == 500
    assert r.json()["error"]["type"] == "server_error"


def test_fail_before_stream_and_nonstream_fail_mid_stream(client):
    client.post("/_mock/scenario", json={"model": TERRA, "mode": "fail_before_stream", "count": 1})
    assert client.post("/v1/chat/completions", json={**BODY, "stream": True}).status_code == 503
    client.post("/_mock/scenario", json={"model": TERRA, "mode": "fail_mid_stream", "count": 1})
    assert client.post("/v1/chat/completions", json=BODY).status_code == 500


def test_slow_waits_delay_then_succeeds(client):
    import time

    client.post("/_mock/scenario", json={"model": TERRA, "mode": "slow", "count": 1, "delay_ms": 200})
    t0 = time.monotonic()
    r = client.post("/v1/chat/completions", json=BODY)
    assert r.status_code == 200
    assert time.monotonic() - t0 >= 0.19


def test_fail_mid_stream_sends_two_chunks_then_breaks(client):
    client.post("/_mock/scenario", json={"model": TERRA, "mode": "fail_mid_stream", "count": 1})
    seen = []
    with pytest.raises(Exception):
        with client.stream("POST", "/v1/chat/completions", json={**BODY, "stream": True}) as r:
            for line in r.iter_lines():
                seen.append(line)
    payloads = sse_data(seen)
    assert len(payloads) == 2
    assert "[DONE]" not in payloads
    # next request is back to ok
    assert client.post("/v1/chat/completions", json=BODY).status_code == 200


def test_fail_mid_stream_waits_delay_after_chunks_before_breaking(client):
    import time

    client.post(
        "/_mock/scenario",
        json={"model": TERRA, "mode": "fail_mid_stream", "count": 1, "delay_ms": 300},
    )
    seen = []
    t0 = time.monotonic()
    first_chunk_at = None
    with pytest.raises(Exception):
        with client.stream("POST", "/v1/chat/completions", json={**BODY, "stream": True}) as r:
            for line in r.iter_lines():
                if first_chunk_at is None and line.startswith("data: "):
                    first_chunk_at = time.monotonic() - t0
                seen.append(line)
    assert len(sse_data(seen)) == 2
    # Chunks are sent right away; only the break waits, so a reader sees them first.
    assert first_chunk_at is not None and first_chunk_at < 0.25
    assert time.monotonic() - t0 >= 0.29


def test_requests_recorded_with_auth_hash_not_raw(client):
    client.post(
        "/v1/chat/completions",
        json={**BODY, "tools": [{"type": "function", "function": {"name": "f"}}]},
        headers={"Authorization": "Bearer sk-super-secret"},
    )
    raw = client.get("/_mock/requests")
    assert "sk-super-secret" not in raw.text
    (entry,) = raw.json()
    assert set(entry) == {"model", "stream", "has_tools", "ts", "auth_hash"}
    assert entry["model"] == TERRA
    assert entry["stream"] is False
    assert entry["has_tools"] is True
    assert len(entry["auth_hash"]) == 16
    import hashlib

    assert entry["auth_hash"] == hashlib.sha256(b"Bearer sk-super-secret").hexdigest()[:16]


def test_reset_clears_everything(client):
    client.post("/_mock/scenario", json={"model": TERRA, "mode": "error_500", "count": 5})
    client.post("/_mock/usage", json={"prompt_tokens": 1, "completion_tokens": 1})
    client.post("/v1/chat/completions", json=BODY)
    client.post("/_mock/reset")
    assert client.get("/_mock/requests").json() == []
    data = client.post("/v1/chat/completions", json=BODY).json()
    assert data["usage"]["prompt_tokens"] == 1000
    assert data["usage"]["completion_tokens"] == 500
