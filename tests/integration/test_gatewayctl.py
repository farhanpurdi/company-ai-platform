"""gatewayctl against the running local stack (spec 8.1, integration layer)."""

from __future__ import annotations

import json
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
import yaml
from gatewayctl.client import ApiError

from helpers import LOCAL_ENTITLEMENTS, REPLICAS, admin, chat, gateway, issue_key, replica, run_ctl

# Spec 8.1: the mock is reset before every test, so no scenario left by an
# earlier (interrupted) run can change the traffic these tests send.
pytestmark = pytest.mark.usefixtures("mock")

REVOCATION_TIMEOUT_S = 300
POLL_INTERVAL_S = 5
UNMANAGED_TEAM = "legacy-x"
FRESH_TEAM = "tmp-fresh"


def _ok(result) -> None:
    assert result.returncode == 0, result.stderr


def test_apply_is_idempotent(applied):
    _ok(run_ctl("apply", "--confirm"))
    plan = run_ctl("plan")
    assert plan.returncode == 0, plan.stderr


def test_litellm_fields_roundtrip(applied):
    key = issue_key("dev1@local.test")
    info = admin().key_info(key)["info"]
    assert {(b["budget_duration"], b["max_budget"]) for b in info["budget_limits"]} == {
        ("24h", 10),
        ("30d", 100),
    }
    assert info["metadata"]["managed_by"] == "gatewayctl"
    assert info["rpm_limit"] == 60
    assert info["team_id"] == "it-developer"

    team = admin().team_info("it-developer")
    assert team["team_info"]["metadata"]["managed_by"] == "gatewayctl"
    members = team["team_memberships"]
    dev1 = [m for m in members if m["user_id"] == "dev1@local.test"]
    assert len(dev1) == 1
    assert dev1[0]["litellm_budget_table"]["max_budget"] == 100


def _write(path: Path, doc: dict) -> Path:
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _wait_for_status(key: str, status: int) -> dict[str, int]:
    """Poll every replica directly until all of them return `status` (no load balancer in front)."""
    deadline = time.monotonic() + REVOCATION_TIMEOUT_S
    with ExitStack() as stack:
        clients = {name: stack.enter_context(replica(name, key)) for name in REPLICAS}
        while True:
            last = {name: chat(client, "company-fast").status_code for name, client in clients.items()}
            if all(code == status for code in last.values()) or time.monotonic() >= deadline:
                return last
            time.sleep(POLL_INTERVAL_S)


def test_removed_member_is_offboarded(applied, tmp_path):
    original = yaml.safe_load(LOCAL_ENTITLEMENTS.read_text(encoding="utf-8"))
    with_member = json.loads(json.dumps(original))
    with_member["teams"]["it-developer"]["members"].append("tmp-off@local.test")
    file_with = _write(tmp_path / "with-member.yaml", with_member)
    file_without = _write(tmp_path / "without-member.yaml", original)

    try:
        _ok(run_ctl("apply", file=file_with))
        key = issue_key("tmp-off@local.test", file=file_with)
        with gateway(key) as client:
            assert chat(client, "company-fast").status_code == 200

        plan = run_ctl("plan", file=file_without)
        assert plan.returncode == 2, plan.stderr
        assert "block_key" in plan.stderr
        assert "remove_member" in plan.stderr

        assert run_ctl("apply", file=file_without).returncode == 4
        _ok(run_ctl("apply", "--confirm", file=file_without))
        members = admin().team_info("it-developer")["team_memberships"]
        assert "tmp-off@local.test" not in {m["user_id"] for m in members}
        assert _wait_for_status(key, 401) == {name: 401 for name in REPLICAS}
    finally:
        restore = run_ctl("apply", "--confirm")
    _ok(restore)
    plan = run_ctl("plan")
    assert plan.returncode == 0, plan.stderr


def test_new_team_applies_without_confirm(applied, tmp_path):
    # LiteLLM adds the master key's identity (default_user_id) to every team it creates;
    # that must not surface as a destructive remove_member on the next plan or apply.
    original = yaml.safe_load(LOCAL_ENTITLEMENTS.read_text(encoding="utf-8"))
    with_team = json.loads(json.dumps(original))
    with_team["teams"][FRESH_TEAM] = {
        "models": ["company-fast"],
        "budget": {"max_usd": 10, "duration": "30d"},
        "rpm_limit": 60,
        "members": ["tmp-fresh@local.test"],
    }
    file_with = _write(tmp_path / "with-team.yaml", with_team)

    _delete_team(FRESH_TEAM)
    try:
        _ok(run_ctl("apply", file=file_with))
        plan = run_ctl("plan", file=file_with)
        assert plan.returncode == 0, plan.stderr
        _ok(run_ctl("apply", file=file_with))
    finally:
        restore = run_ctl("apply", "--confirm", "--prune")
    _ok(restore)
    plan = run_ctl("plan", "--prune")
    assert plan.returncode == 0, plan.stderr


def _team_snapshot(team_id: str) -> dict:
    info = admin().team_info(team_id)["team_info"]
    fields = ("team_id", "team_alias", "models", "max_budget", "budget_duration", "rpm_limit", "metadata", "blocked")
    return {f: info.get(f) for f in fields}


def _delete_team(team_id: str) -> None:
    try:
        admin().team_delete(team_id)
    except ApiError as exc:
        if exc.status not in (400, 404):
            raise


def test_unmanaged_team_untouched(applied):
    # A leftover from an interrupted run would otherwise make team_new fail.
    _delete_team(UNMANAGED_TEAM)
    admin().team_new({"team_id": UNMANAGED_TEAM, "models": ["company-fast"]})
    try:
        before = _team_snapshot(UNMANAGED_TEAM)
        assert (before["metadata"] or {}).get("managed_by") is None

        plan = run_ctl("plan", "--json")
        assert plan.returncode == 0, plan.stderr
        doc = json.loads(plan.stderr)
        assert f"team:{UNMANAGED_TEAM}" in doc["unmanaged"]
        assert not any(a["target"] == f"team:{UNMANAGED_TEAM}" for a in doc["actions"])

        _ok(run_ctl("apply", "--confirm"))
        assert _team_snapshot(UNMANAGED_TEAM) == before
    finally:
        _delete_team(UNMANAGED_TEAM)
