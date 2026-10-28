import json

import pytest

from fakes import RecordingClient
from gatewayctl.apply import ApplyError, execute
from gatewayctl.audit import AuditLog
from gatewayctl.diff import Action, Plan

MANAGED = {"managed_by": "gatewayctl"}

TEAM = {
    "team_id": "dev",
    "alias": "Dev",
    "models": ["company-coding", "company-fast"],
    "max_budget": 500.0,
    "budget_duration": "30d",
    "rpm_limit": 600,
}


def plan_of(*actions):
    return Plan(tuple(actions), (), ())


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.log", operator="ops@example.com", git_sha="sha1")


def audit_lines(audit):
    return [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]


def test_execute_calls_in_plan_order_and_audits(audit):
    member = {"team_id": "dev", "user_id": "budi@x.com", "max_budget_in_team": 100.0}
    key_before = {
        "token": "tok1",
        "models": ["company-fast"],
        "rpm_limit": 10,
        "budgets": [],
    }
    key_after = {
        "token": "tok1",
        "models": ["company-coding", "company-fast"],
        "rpm_limit": 60,
        "budgets": [{"duration": "24h", "max_usd": 10}, {"duration": "30d", "max_usd": 100}],
    }
    old_member = {"team_id": "old", "user_id": "gone@x.com", "max_budget_in_team": None}
    plan = plan_of(
        Action("create_team", "team:dev", None, TEAM, False),
        Action("update_team", "team:ops", TEAM, TEAM, False),
        Action("add_member", "member:dev/budi@x.com", None, member, False),
        Action("update_member", "member:dev/budi@x.com", member, {**member, "max_budget_in_team": 50.0}, False),
        Action("update_key", "key:budi-x", key_before, key_after, False),
        Action("block_key", "key:gone-x", {"token": "tok2", "key_alias": "gone-x"}, None, True),
        Action("remove_member", "member:old/gone@x.com", old_member, None, True),
        Action("delete_team", "team:old", {**TEAM, "team_id": "old"}, None, True),
    )
    client = RecordingClient()

    assert execute(plan, client, audit) == 8

    assert client.names == [
        "team_new",
        "team_update",
        "member_add",
        "member_update",
        "key_update",
        "key_block",
        "member_delete",
        "team_delete",
    ]
    assert client.calls[2] == ("member_add", "dev", "budi@x.com", 100.0)
    assert client.calls[3] == ("member_update", "dev", "budi@x.com", 50.0)
    assert client.calls[4][1] == {
        "key": "tok1",
        "models": ["company-coding", "company-fast"],
        "rpm_limit": 60,
        "budget_limits": [
            {"budget_duration": "24h", "max_budget": 10},
            {"budget_duration": "30d", "max_budget": 100},
        ],
        "metadata": MANAGED,
    }
    assert client.calls[5] == ("key_block", "tok2")
    assert client.calls[6] == ("member_delete", "old", "gone@x.com")
    assert client.calls[7] == ("team_delete", "old")

    lines = audit_lines(audit)
    assert [(entry["action"], entry["target"]) for entry in lines] == [
        (a.kind, a.target) for a in plan.actions
    ]
    assert lines[0]["operator"] == "ops@example.com"
    assert lines[0]["git_sha"] == "sha1"
    assert lines[0]["after"] == TEAM


def test_create_team_payload_has_managed_metadata(audit):
    client = RecordingClient()
    execute(plan_of(Action("create_team", "team:dev", None, TEAM, False)), client, audit)
    assert client.calls == [
        (
            "team_new",
            {
                "team_id": "dev",
                "team_alias": "Dev",
                "models": ["company-coding", "company-fast"],
                "max_budget": 500.0,
                "budget_duration": "30d",
                "rpm_limit": 600,
                "metadata": MANAGED,
            },
        )
    ]


def test_execute_stops_on_first_failure(audit):
    member = {"team_id": "dev", "user_id": "a@x.com", "max_budget_in_team": 1.0}
    plan = plan_of(
        Action("create_team", "team:dev", None, TEAM, False),
        Action("add_member", "member:dev/a@x.com", None, member, False),
        Action("add_member", "member:dev/b@x.com", None, {**member, "user_id": "b@x.com"}, False),
    )
    client = RecordingClient(fail_on_call=2)

    with pytest.raises(ApplyError) as info:
        execute(plan, client, audit)

    assert info.value.done == 1
    assert info.value.action == plan.actions[1]
    assert info.value.cause.status == 500
    assert len(client.calls) == 2
    assert len(audit_lines(audit)) == 1


def test_empty_plan_is_noop(audit):
    assert execute(plan_of(), RecordingClient(), audit) == 0
    assert not audit.path.exists()


def test_audit_failure_after_call_names_the_applied_action(audit, monkeypatch):
    from gatewayctl.apply import AuditWriteError

    member = {"team_id": "dev", "user_id": "a@x.com", "max_budget_in_team": 1.0}
    plan = plan_of(
        Action("create_team", "team:dev", None, TEAM, False),
        Action("add_member", "member:dev/a@x.com", None, member, False),
    )
    real_record = AuditLog.record
    calls = []

    def flaky(self, *args):
        calls.append(args)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        real_record(self, *args)

    monkeypatch.setattr(AuditLog, "record", flaky)
    client = RecordingClient()
    with pytest.raises(AuditWriteError) as info:
        execute(plan, client, audit)
    assert info.value.done == 1
    assert info.value.action == plan.actions[1]
    assert client.names == ["team_new", "member_add"]
