"""gatewayctl against the running local stack (spec 8.1, integration layer)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from helpers import LOCAL_ENTITLEMENTS, admin, chat, gateway, issue_key, run_ctl
from gatewayctl.client import ApiError

REVOCATION_TIMEOUT_S = 300
POLL_INTERVAL_S = 5
UNMANAGED_TEAM = "legacy-x"


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


def _wait_for_status(key: str, status: int) -> int:
    """Poll through Caddy until two consecutive responses (both replicas) return `status`."""
    deadline = time.monotonic() + REVOCATION_TIMEOUT_S
    streak = 0
    last = None
    with gateway(key) as client:
        while True:
            last = chat(client, "company-fast").status_code
            streak = streak + 1 if last == status else 0
            if streak >= 2 or time.monotonic() >= deadline:
                return last
            if streak == 0:
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
        assert _wait_for_status(key, 401) == 401
    finally:
        restore = run_ctl("apply", "--confirm")
    _ok(restore)
    plan = run_ctl("plan")
    assert plan.returncode == 0, plan.stderr


def _team_snapshot(team_id: str) -> dict:
    info = admin().team_info(team_id)["team_info"]
    fields = ("team_id", "team_alias", "models", "max_budget", "budget_duration", "rpm_limit", "metadata", "blocked")
    return {f: info.get(f) for f in fields}


def _delete_unmanaged_team() -> None:
    try:
        admin().team_delete(UNMANAGED_TEAM)
    except ApiError as exc:
        if exc.status not in (400, 404):
            raise


def test_unmanaged_team_untouched(applied):
    # A leftover from an interrupted run would otherwise make team_new fail.
    _delete_unmanaged_team()
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
        _delete_unmanaged_team()
