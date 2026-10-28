"""T05: a blocked key is rejected by every replica within the target time (spec 8.2, 10)."""

from __future__ import annotations

import time

from helpers import admin, chat, issue_key, replica, run_ctl

REPLICAS = ("litellm-a", "litellm-b")
REVOCATION_TARGET_S = 300
POLL_INTERVAL_S = 5


def test_t05_block_propagates_to_all_replicas(applied, mock, capsys):
    key = issue_key("dev2@local.test")
    alias = admin().key_info(key)["info"]["key_alias"]
    clients = {name: replica(name, key) for name in REPLICAS}
    try:
        # Warm each replica's key cache so the test covers cache invalidation.
        for name, client in clients.items():
            r = chat(client, "company-fast")
            assert r.status_code == 200, f"{name}: {r.status_code} {r.text}"

        block = run_ctl("key", "block", "--alias", alias)
        assert block.returncode == 0, block.stderr
        started = time.monotonic()

        while True:
            statuses = {name: chat(client, "company-fast").status_code for name, client in clients.items()}
            elapsed = time.monotonic() - started
            if all(s == 401 for s in statuses.values()) or elapsed >= REVOCATION_TARGET_S:
                break
            time.sleep(POLL_INTERVAL_S)
    finally:
        for client in clients.values():
            client.close()

    # Shown even when the test passes: the time is recorded for Gate 2.
    with capsys.disabled():
        print(f"\nT05 revocation seconds={elapsed:.0f} statuses={statuses}")
    assert all(s == 401 for s in statuses.values()), statuses
    assert elapsed <= REVOCATION_TARGET_S
