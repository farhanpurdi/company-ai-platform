"""Shared helpers for integration and acceptance tests. Run inside the `tools` container."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Literal

import httpx

from gatewayctl.client import LiteLLMClient

REPO = Path(__file__).resolve().parents[1]
LOCAL_ENTITLEMENTS = REPO / "entitlements" / "local.yaml"
OPERATOR = "test@local"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)
REPLICAS = ("litellm-a", "litellm-b")


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RuntimeError(f"env {name} belum diatur; jalankan uji lewat `make test`")
    return value


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def gateway(key: str) -> httpx.Client:
    """Client for the address users reach: litellm-a directly (spec 4.2). httpx never retries by itself."""
    return httpx.Client(base_url=_env("GATEWAY_URL"), headers=_auth(key), timeout=TIMEOUT)


def replica(name: Literal["litellm-a", "litellm-b"], key: str) -> httpx.Client:
    """Client for one LiteLLM replica by its service name on the compose network."""
    return httpx.Client(base_url=f"http://{name}:4000", headers=_auth(key), timeout=TIMEOUT)


def chat(
    client: httpx.Client,
    model: str,
    *,
    stream: bool = False,
    tools: list | None = None,
    tool_choice: str | dict | None = None,
    prompt: str = "ping",
    max_tokens: int | None = None,
) -> httpx.Response:
    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if stream:
        body["stream"] = True
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools is not None:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if not stream:
        return client.post("/v1/chat/completions", json=body)
    # A stream that breaks mid-body still yields a Response with whatever arrived;
    # extensions["stream_error"] names the transport error.
    chunks: list[bytes] = []
    error: str | None = None
    with client.stream("POST", "/v1/chat/completions", json=body) as r:
        try:
            for chunk in r.iter_bytes():
                chunks.append(chunk)
        except httpx.TransportError as exc:
            error = type(exc).__name__
        headers = {
            k: v
            for k, v in r.headers.items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        }
        return httpx.Response(
            r.status_code,
            headers=headers,
            content=b"".join(chunks),
            request=r.request,
            extensions={"stream_error": error},
        )


class Mock:
    """Control API of the mock upstream (spec 7)."""

    def __init__(self, base_url: str | None = None) -> None:
        self._http = httpx.Client(base_url=base_url or _env("MOCK_URL"), timeout=30.0)

    def reset(self) -> None:
        self._http.post("/_mock/reset").raise_for_status()

    def scenario(self, model: str, mode: str, count: int, delay_ms: int = 0) -> None:
        self._http.post(
            "/_mock/scenario",
            json={"model": model, "mode": mode, "count": count, "delay_ms": delay_ms},
        ).raise_for_status()

    def requests(self) -> list[dict]:
        r = self._http.get("/_mock/requests")
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._http.close()


def run_ctl(*args: str, file: Path = LOCAL_ENTITLEMENTS) -> subprocess.CompletedProcess:
    """Run the gatewayctl CLI as an operator would. Only `key issue` writes to stdout."""
    env = {**os.environ, "GATEWAYCTL_OPERATOR": OPERATOR}
    return subprocess.run(
        ["gatewayctl", "--file", str(file), *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def issue_key(user: str, *, file: Path = LOCAL_ENTITLEMENTS) -> str:
    """Issue a fresh key with a unique label; returns the raw key (never logged)."""
    label = f"t-{uuid.uuid4().hex[:6]}"
    result = run_ctl("key", "issue", "--user", user, "--label", label, file=file)
    if result.returncode != 0:
        raise AssertionError(f"key issue {user} gagal (exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def admin() -> LiteLLMClient:
    return LiteLLMClient(_env("LITELLM_BASE_URL"), _env("LITELLM_MASTER_KEY"))
