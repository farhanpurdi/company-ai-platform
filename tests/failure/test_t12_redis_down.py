"""T12: Redis down (spec Fase 2 section 6). Run by scripts/failure-tests.sh, one phase per call.

The script stops Redis between `prepare` and `redis_down` and starts it again before
`recovered`. Keys arrive through the environment: they never appear on a command line.
"""

from __future__ import annotations

import os
import time

from helpers import MOCK_COMPLETION_TOKENS, chat, gateway

RPM_LIMIT = 3  # rate1@local.test key rpm_limit in entitlements/local.yaml
RPM_REQUESTS = 6
BUDGET_REQUESTS = 3
PREPARE_MAX_REQUESTS = 30
PREPARE_PAUSE_S = 1.0  # as in T02: lets spend settle between requests
POLL_S = 5.0
RECOVERY_LIMIT_S = 120.0


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError("jalankan lewat make test-failure")
    return value


def test_t12_prepare(applied, mock):
    last = None
    with gateway(_env("T12_BUDGET_KEY")) as c:
        for _ in range(PREPARE_MAX_REQUESTS):
            last = chat(c, "company-fast", max_tokens=MOCK_COMPLETION_TOKENS)
            if last.status_code != 200:
                break
            time.sleep(PREPARE_PAUSE_S)
    assert last is not None and last.status_code != 200, "budget key belum habis setelah persiapan"


def test_t12_redis_down(mock, capsys):
    # No `applied` fixture: apply needs a healthy Redis.
    ok_rpm = 0
    with gateway(_env("T12_RPM_KEY")) as c:
        for _ in range(RPM_REQUESTS):
            if chat(c, "company-fast").status_code == 200:
                ok_rpm += 1
    ok_budget = 0
    with gateway(_env("T12_BUDGET_KEY")) as c:
        for _ in range(BUDGET_REQUESTS):
            if chat(c, "company-fast", max_tokens=MOCK_COMPLETION_TOKENS).status_code == 200:
                ok_budget += 1
    behavior = "rejected" if ok_rpm == 0 else "enforced"
    with capsys.disabled():
        print(f"T12 behavior={behavior} ok={ok_rpm} rejected={RPM_REQUESTS - ok_rpm} budget_ok={ok_budget}")
    assert ok_rpm <= RPM_LIMIT, f"{ok_rpm} request lolos, rpm_limit {RPM_LIMIT}"
    assert ok_budget == 0, "key dengan budget habis masih diterima saat Redis mati"


def test_t12_recovered(mock, capsys):
    started = time.monotonic()
    status = None
    with gateway(_env("T12_RPM_KEY")) as c:
        while time.monotonic() - started <= RECOVERY_LIMIT_S:
            status = chat(c, "company-fast").status_code
            if status == 200:
                break
            time.sleep(POLL_S)
    seconds = round(time.monotonic() - started)
    with capsys.disabled():
        print(f"T12 recovery seconds={seconds}")
    assert status == 200, f"belum pulih setelah {RECOVERY_LIMIT_S:.0f} detik (status terakhir {status})"
