"""T13: Postgres down (spec Fase 2 section 6). Run by scripts/failure-tests.sh, one phase per call.

A key LiteLLM already cached keeps working for a while, a key it has never seen is
refused at once (fail closed), and the cached key must be refused within 300 seconds.
"""

from __future__ import annotations

import os
import time

from helpers import chat, gateway

POLL_S = 5.0
CACHED_KEY_LIMIT_S = 300.0
RECOVERY_LIMIT_S = 120.0


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError("jalankan lewat make test-failure")
    return value


def test_t13_prepare(applied, mock):
    with gateway(_env("T13_WARM_KEY")) as c:
        assert chat(c, "company-fast").status_code == 200


def test_t13_postgres_down(mock, capsys):
    with gateway(_env("T13_FRESH_KEY")) as c:
        assert chat(c, "company-fast").status_code != 200, "key yang belum pernah dipakai diterima tanpa Postgres"
    started = time.monotonic()
    status = 200
    with gateway(_env("T13_WARM_KEY")) as c:
        while time.monotonic() - started <= CACHED_KEY_LIMIT_S:
            status = chat(c, "company-fast").status_code
            if status != 200:
                break
            time.sleep(POLL_S)
    seconds = round(time.monotonic() - started)
    with capsys.disabled():
        print(f"T13 cached_key_seconds={seconds}")
    assert status != 200, f"key yang di-cache masih diterima setelah {CACHED_KEY_LIMIT_S:.0f} detik"
    assert seconds <= CACHED_KEY_LIMIT_S


def test_t13_recovered(mock, capsys):
    started = time.monotonic()
    status = None
    with gateway(_env("T13_WARM_KEY")) as c:
        while time.monotonic() - started <= RECOVERY_LIMIT_S:
            status = chat(c, "company-fast").status_code
            if status == 200:
                break
            time.sleep(POLL_S)
    seconds = round(time.monotonic() - started)
    with capsys.disabled():
        print(f"T13 recovery seconds={seconds}")
    assert status == 200, f"belum pulih setelah {RECOVERY_LIMIT_S:.0f} detik (status terakhir {status})"
