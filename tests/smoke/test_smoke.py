"""T06 (streaming) and T07 (tool calling) through the gateway (spec 8.3).

Meant for the VM profile against real OpenAI (`make smoke ENV=vm`); on the local
profile it only proves the test code against the mock upstream.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from helpers import chat, gateway

MODELS = ["company-coding", "company-reasoning"]
MIN_CHUNKS = 5
MAX_FIRST_TOKEN_SECONDS = 30
TIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "Return the current time.",
        "parameters": {"type": "object", "properties": {}},
    },
}


@pytest.fixture(scope="module")
def smoke_key() -> str:
    key = os.environ.get("SMOKE_KEY", "")
    if not key:
        pytest.skip(
            "SMOKE_KEY belum diisi; terbitkan dengan `make ctl ARGS='key issue --user smoke@perusahaan.com --label smoke'`"
        )
    return key


def _stream_chunks(key: str, model: str) -> tuple[list[dict], float]:
    """Content-bearing chunks of a streamed answer and the seconds until the first one."""
    body = {
        "model": model,
        "stream": True,
        "messages": [{"role": "user", "content": "count from 1 to 20"}],
    }
    chunks: list[dict] = []
    first: float | None = None
    started = time.monotonic()
    with gateway(key) as client, client.stream("POST", "/v1/chat/completions", json=body) as r:
        assert r.status_code == 200, r.read().decode()[:300]
        for line in r.iter_lines():
            if not line.startswith("data:") or line.strip() == "data: [DONE]":
                continue
            chunk = json.loads(line[len("data:") :])
            choices = chunk.get("choices") or []
            if choices and (choices[0].get("delta") or {}).get("content"):
                if first is None:
                    first = time.monotonic() - started
                chunks.append(chunk)
    assert first is not None, "stream tidak berisi token"
    return chunks, first


@pytest.mark.parametrize("model", MODELS)
def test_t06_streaming(smoke_key, model):
    chunks, first_token_seconds = _stream_chunks(smoke_key, model)
    print(f"T06 {model} chunks={len(chunks)} first_token={first_token_seconds:.1f}s")
    assert len(chunks) >= MIN_CHUNKS
    assert first_token_seconds < MAX_FIRST_TOKEN_SECONDS


@pytest.mark.parametrize("model", MODELS)
def test_t07_tool_calling(smoke_key, model):
    with gateway(smoke_key) as client:
        r = chat(client, model, tools=[TIME_TOOL], prompt="What time is it? Use the tool.")
    assert r.status_code == 200, r.text[:300]
    tool_calls = r.json()["choices"][0]["message"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "get_current_time"
