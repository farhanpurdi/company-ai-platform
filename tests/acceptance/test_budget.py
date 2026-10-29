"""T02 (budget exhausted) and T03 (parallel overshoot) against the mock upstream (spec 8.2).

One mock request on company-fast costs $0.01 (1000 input + 500 output tokens on Terra).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

from helpers import REPLICAS, admin, chat, gateway, issue_key, replica

REQUEST_COST_USD = 0.01
T02_MAX_REQUESTS = 30
T02_PAUSE_S = 1.0
# Budget enforcement fails closed (spec 5): a request is admitted only if its
# worst-case cost fits. 500 output tokens reserve $0.0075, so the fifth $0.01
# request still fits $0.05; without max_tokens the 16384-token reservation
# ($0.25) is larger than the whole budget.
T02_MAX_TOKENS = 500
T03_LIMIT_USD = 0.10
T03_PARALLEL = 20
T03_TOLERANCE = 0.10
# LiteLLM reserves each request's worst-case cost before calling upstream. Without
# max_tokens that is 16384 output tokens ($0.25), more than the whole key budget,
# so requests are admitted one at a time and the run never nears the limit. 700
# output tokens reserve $0.0105, just over the mock's real $0.01.
T03_MAX_TOKENS = 700
SPEND_POLL_S = 2.0
SPEND_WAIT_S = 30.0


def test_t02_budget_exhausted(applied, mock):
    successes = 0
    last = None
    with gateway(issue_key("budget1@local.test")) as client:
        for _ in range(T02_MAX_REQUESTS):
            last = chat(client, "company-fast", max_tokens=T02_MAX_TOKENS)
            if last.status_code != 200:
                break
            successes += 1
            time.sleep(T02_PAUSE_S)
    print(f"T02 successes={successes} last_status={last.status_code}")
    assert successes >= 5
    assert last.status_code != 200, f"masih 200 setelah {T02_MAX_REQUESTS} request"
    assert "budget_exceeded" in last.text, last.text


def _key_spend(key: str) -> float:
    return float(admin().key_info(key)["info"].get("spend") or 0.0)


def _settled_spend(key: str, expected_min: float) -> float:
    """Read key spend every SPEND_POLL_S until two consecutive reads agree.

    A read below expected_min (spend of the requests the mock already answered)
    means the spend writer has not flushed yet, so it never counts as settled;
    if it never settles the test fails rather than report a low overshoot.
    """
    deadline = time.monotonic() + SPEND_WAIT_S
    previous = None
    while True:
        spend = _key_spend(key)
        if spend == previous and spend >= expected_min - 1e-9:
            return spend
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"spend key belum stabil setelah {SPEND_WAIT_S:.0f} detik: "
                f"terbaca {spend:.4f}, minimal {expected_min:.4f}"
            )
        previous = spend
        time.sleep(SPEND_POLL_S)


def test_t03_parallel_overshoot_within_tolerance(applied, mock, capsys):
    key = issue_key("parallel1@local.test")
    # Spread evenly over both replicas (spec 8.2): without a load balancer the
    # test does it, so the budget counter is still shared across two processes.
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=T03_PARALLEL) as pool:
        clients = [stack.enter_context(replica(name, key)) for name in REPLICAS]
        responses = list(
            pool.map(
                lambda i: chat(clients[i % len(clients)], "company-fast", max_tokens=T03_MAX_TOKENS),
                range(T03_PARALLEL),
            )
        )
    upstream = len(mock.requests())
    upstream_cost = upstream * REQUEST_COST_USD
    # The mock knows the true cost; recorded spend can only lag behind it.
    spend = max(_settled_spend(key, upstream_cost), upstream_cost)
    overshoot = (spend - T03_LIMIT_USD) / T03_LIMIT_USD
    ok = sum(r.status_code == 200 for r in responses)
    # Shown even when the test passes: the numbers are recorded for Gate 2.
    with capsys.disabled():
        print(
            f"\nT03 spend={spend:.4f} overshoot={overshoot:.1%} "
            f"ok={ok} rejected={T03_PARALLEL - ok} upstream={upstream}"
        )
    # Any rejection other than the budget check would make the overshoot meaningless.
    rejected = [r for r in responses if r.status_code != 200]
    assert all("budget_exceeded" in r.text for r in rejected), [r.status_code for r in rejected]
    # All rejected would pass trivially (e.g. team budget used up before the run).
    # Stopping a little below the limit is allowed: in-flight reservations count
    # against the window budget, so LiteLLM may reject early.
    assert ok >= 1 and upstream >= 1, "tidak ada request yang lolos; budget sudah habis sebelum uji?"
    # A run that ends far below the limit says nothing about overshoot (spec 8.2: near the limit).
    assert spend >= T03_LIMIT_USD / 2, f"spend {spend:.4f} tidak mendekati limit {T03_LIMIT_USD}; uji tidak bermakna"
    assert overshoot <= T03_TOLERANCE
