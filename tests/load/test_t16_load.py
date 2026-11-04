"""T16: the gateway adds at most 1 s to the p95 time to first token at 25 and 50 parallel streams.

Each wave sends N streams at once through the gateway (company-coding) and then the same
N streams straight to the mock upstream; the difference of the two p95 values is the
gateway's overhead. Run by `make loadtest`; numbers from a laptop are for development,
the official ones come from the VM (docs/gate3-checklist.md).
"""

from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from helpers import (
    MOCK_COMPLETION_TOKENS,
    MOCK_PROMPT_TOKENS,
    TIMEOUT,
    _env,
    chat,
    gateway,
    issue_key,
    model_prices,
    settled_key_spend,
)

LEVELS = (25, 50)
WAVES = 4
MAX_OVERHEAD_S = 1.0
ALIAS = "company-coding"
MOCK_MODEL = "gpt-5.6-terra"  # the upstream model behind company-coding
BARRIER_TIMEOUT_S = 60.0

PRICES = model_prices(ALIAS)
REQUEST_COST_USD = (
    MOCK_PROMPT_TOKENS * PRICES["input_cost_per_token"] + MOCK_COMPLETION_TOKENS * PRICES["output_cost_per_token"]
)


def ttft(client: httpx.Client, model: str) -> tuple[bool, float]:
    """(ok, seconds from sending to the first data line with content).

    ok only when the status is 200 and the stream ends with `data: [DONE]`.
    """
    body = {"model": model, "stream": True, "messages": [{"role": "user", "content": "ping"}]}
    started = time.monotonic()
    first: float | None = None
    done = False
    try:
        with client.stream("POST", "/v1/chat/completions", json=body) as r:
            if r.status_code != 200:
                return False, time.monotonic() - started
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    done = True
                    break
                if first is None:
                    choices = json.loads(payload).get("choices") or []
                    if choices and (choices[0].get("delta") or {}).get("content"):
                        first = time.monotonic() - started
    except httpx.HTTPError:
        return False, time.monotonic() - started
    return (done and first is not None), (first if first is not None else time.monotonic() - started)


def _wave(client: httpx.Client, model: str, n: int) -> list[tuple[bool, float]]:
    barrier = threading.Barrier(n)

    def one(_: int) -> tuple[bool, float]:
        barrier.wait(timeout=BARRIER_TIMEOUT_S)
        return ttft(client, model)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(one, range(n)))


def p95(values: list[float]) -> float:
    """Nearest rank."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def test_t16_first_token_overhead(applied, mock, capsys):
    key = issue_key("load1@local.test")
    # Warm up: connection pools, key cache and the first Prometheus label sets.
    with gateway(key) as warm:
        assert chat(warm, ALIAS).status_code == 200
    mock.reset()

    rows = []
    total_requests = 0
    with gateway(key) as via_gateway, httpx.Client(base_url=_env("MOCK_URL"), timeout=TIMEOUT) as direct:
        for n in LEVELS:
            gw: list[tuple[bool, float]] = []
            base: list[tuple[bool, float]] = []
            for _ in range(WAVES):
                gw += _wave(via_gateway, ALIAS, n)
                base += _wave(direct, MOCK_MODEL, n)
            total_requests += len(gw)
            gw_ok = [t for ok, t in gw if ok]
            base_ok = [t for ok, t in base if ok]
            rows.append(
                {
                    "n": n,
                    "requests": len(gw),
                    "errors": len(gw) - len(gw_ok),
                    "direct_errors": len(base) - len(base_ok),
                    "gateway": p95(gw_ok) if gw_ok else math.inf,
                    "direct": p95(base_ok) if base_ok else math.inf,
                }
            )

    with capsys.disabled():
        for r in rows:
            print(
                f"T16 concurrency={r['n']} requests={r['requests']} "
                f"p95_ttft_gateway_s={r['gateway']:.3f} p95_ttft_direct_s={r['direct']:.3f} "
                f"p95_ttft_overhead_s={r['gateway'] - r['direct']:.3f} errors={r['errors']}"
            )

    for r in rows:
        assert r["direct_errors"] == 0, f"baseline langsung ke mock tidak sah di {r['n']} stream: {r['direct_errors']} gagal"
        assert r["errors"] == 0, f"{r['errors']} dari {r['requests']} stream lewat gateway gagal di {r['n']} stream"
        overhead = r["gateway"] - r["direct"]
        assert overhead <= MAX_OVERHEAD_S, f"selisih p95 token pertama {overhead:.3f} s > {MAX_OVERHEAD_S} s di {r['n']} stream"

    # Every admitted stream is billed exactly once (+1 for the warm-up request).
    expected = (total_requests + 1) * REQUEST_COST_USD
    spend = settled_key_spend(key, expected)
    assert math.isclose(spend, expected, rel_tol=1e-6), f"spend {spend} != {expected}"
