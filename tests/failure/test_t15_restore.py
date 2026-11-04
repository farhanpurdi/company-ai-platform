"""T15: backup, change state, restore, verify (spec Fase 2 section 4). Run by scripts/failure-tests.sh.

Phases: `prepare` (state that must survive), backup, `mutate` (state that must vanish),
`restore.sh`, `verify`. var/t15-before.json holds only non-secret data: team spend, key
aliases and a key's spend. Keys arrive through the environment, never a command line.
"""

from __future__ import annotations

import json
import math
import os
import time

from helpers import (
    MOCK_COMPLETION_TOKENS,
    MOCK_PROMPT_TOKENS,
    REPO,
    admin,
    chat,
    gateway,
    key_spend,
    model_prices,
    settled_key_spend,
)

STATE_FILE = REPO / "var" / "t15-before.json"
PRICES = model_prices("company-fast")
REQUEST_COST_USD = (
    MOCK_PROMPT_TOKENS * PRICES["input_cost_per_token"] + MOCK_COMPLETION_TOKENS * PRICES["output_cost_per_token"]
)
PREPARE_MAX_REQUESTS = 30
PREPARE_PAUSE_S = 1.0  # as in T02
SETTLE_POLL_S = 2.0
SETTLE_WAIT_S = 30.0


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError("jalankan lewat make test-failure")
    return value


def _team_spend() -> dict[str, float]:
    return {t["team_id"]: float(t.get("spend") or 0.0) for t in admin().list_teams()}


def _settled_team_spend() -> dict[str, float]:
    """Team spend once two reads in a row agree: the spend writer has flushed."""
    deadline = time.monotonic() + SETTLE_WAIT_S
    previous = None
    while True:
        current = _team_spend()
        if current == previous:
            return current
        if time.monotonic() >= deadline:
            raise AssertionError(f"spend team belum stabil setelah {SETTLE_WAIT_S:.0f} detik")
        previous = current
        time.sleep(SETTLE_POLL_S)


def _alias(key: str) -> str:
    return admin().key_info(key)["info"]["key_alias"]


def test_t15_prepare(applied, mock):
    old_key = _env("T15_OLD_KEY")
    with gateway(old_key) as c:
        for _ in range(2):
            assert chat(c, "company-fast").status_code == 200
    old_spend = settled_key_spend(old_key, 2 * REQUEST_COST_USD)

    # Exhaust the budget key like T02, and wait until its spend is in the database.
    budget_key = _env("T15_BUDGET_KEY")
    successes = 0
    last = None
    with gateway(budget_key) as c:
        for _ in range(PREPARE_MAX_REQUESTS):
            last = chat(c, "company-fast", max_tokens=MOCK_COMPLETION_TOKENS)
            if last.status_code != 200:
                break
            successes += 1
            time.sleep(PREPARE_PAUSE_S)
    assert last is not None and last.status_code != 200, "budget key belum habis"
    settled_key_spend(budget_key, successes * REQUEST_COST_USD)

    STATE_FILE.write_text(
        json.dumps(
            {
                "teams": _settled_team_spend(),
                "old_key_alias": _alias(old_key),
                "old_key_spend": old_spend,
            }
        )
    )


def test_t15_mutate(mock):
    new_key = _env("T15_NEW_KEY")
    with gateway(new_key) as c:
        assert chat(c, "company-fast").status_code == 200
    spend = settled_key_spend(new_key, REQUEST_COST_USD)
    assert spend > 0
    # The new spend must be in the database before the restore replaces it.
    state = json.loads(STATE_FILE.read_text())
    state["new_key_alias"] = _alias(new_key)
    STATE_FILE.write_text(json.dumps(state))


def test_t15_verify(mock, capsys):
    state = json.loads(STATE_FILE.read_text())
    old_key, new_key, budget_key = _env("T15_OLD_KEY"), _env("T15_NEW_KEY"), _env("T15_BUDGET_KEY")

    # Read spend first: any chat below would change it.
    old_spend = key_spend(old_key)
    teams = _team_spend()
    aliases = {k.get("key_alias") for k in admin().list_keys()}

    assert math.isclose(old_spend, state["old_key_spend"], abs_tol=1e-9), (old_spend, state["old_key_spend"])
    assert teams == state["teams"] or all(
        math.isclose(teams.get(t, math.nan), v, abs_tol=1e-9) for t, v in state["teams"].items()
    ), (teams, state["teams"])
    assert state["old_key_alias"] in aliases
    assert state["new_key_alias"] not in aliases, "key yang dibuat setelah backup masih ada"

    with gateway(new_key) as c:
        assert chat(c, "company-fast").status_code == 401
    with gateway(old_key) as c:
        assert chat(c, "company-fast").status_code == 200
    with gateway(budget_key) as c:
        # Redis was flushed: the budget must be enforced from the restored spend.
        assert chat(c, "company-fast", max_tokens=MOCK_COMPLETION_TOKENS).status_code != 200

    with capsys.disabled():
        print(f"T15 restore ok teams={len(state['teams'])}")
