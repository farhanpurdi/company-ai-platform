import pytest

from gatewayctl.diff import Action, ConflictError, Plan, diff
from gatewayctl.model import (
    ActualKey,
    ActualState,
    BudgetWindow,
    DesiredState,
    KeyPolicy,
    MemberSpec,
    TeamSpec,
)

ALL = ("company-fast", "company-coding", "company-reasoning")
BUDGETS = (BudgetWindow("24h", 10), BudgetWindow("30d", 100))


def team(team_id="dev", *, models=ALL, max_budget=500.0, duration="30d", rpm=600, alias=None):
    return TeamSpec(team_id, alias or team_id.title(), frozenset(models), max_budget, duration, rpm)


def member(user_id, team_id="dev", budget=100.0):
    return MemberSpec(user_id, team_id, budget)


def policy(models=ALL, rpm=60, budgets=BUDGETS):
    return KeyPolicy(frozenset(models), rpm, tuple(budgets))


def key(alias, user, team_id="dev", *, token=None, blocked=False, managed=True, pol=None):
    return ActualKey(
        token=token or f"tok-{alias}-0000",
        key_alias=alias,
        user_id=user,
        team_id=team_id,
        blocked=blocked,
        policy=pol or policy(),
        managed=managed,
    )


def desired(teams, members, policies=None):
    policies = policies if policies is not None else {m.user_id: policy() for m in members}
    return DesiredState(
        teams={t.team_id: t for t in teams},
        members={m.user_id: m for m in members},
        key_policies=policies,
    )


def actual(teams=(), members=(), keys=(), *, managed=None):
    managed = {t.team_id for t in teams} if managed is None else set(managed)
    return ActualState(
        teams={t.team_id: t for t in teams},
        managed_teams=frozenset(managed),
        members=tuple(members),
        keys=tuple(keys),
    )


def kinds(plan):
    return [a.kind for a in plan.actions]


def by_kind(plan, kind):
    return [a for a in plan.actions if a.kind == kind]


def world():
    """Desired and actual states that are already in sync."""
    members = [member("budi@x.com"), member("sari@x.com")]
    want = desired([team()], members)
    have = actual(
        [team()],
        members,
        [key("budi@x.com-laptop", "budi@x.com"), key("sari@x.com-laptop", "sari@x.com")],
    )
    return want, have


def test_empty_actual_creates_everything():
    want = desired([team()], [member("budi@x.com"), member("sari@x.com")])
    plan = diff(want, actual())
    assert kinds(plan) == ["create_team", "add_member", "add_member"]
    assert [a.target for a in plan.actions] == [
        "team:dev",
        "member:dev/budi@x.com",
        "member:dev/sari@x.com",
    ]
    assert not any(a.destructive for a in plan.actions)
    assert plan.actions[0].before is None
    assert plan.actions[0].after == {
        "team_id": "dev",
        "alias": "Dev",
        "models": sorted(ALL),
        "max_budget": 500.0,
        "budget_duration": "30d",
        "rpm_limit": 600,
    }
    assert plan.actions[1].after == {
        "team_id": "dev",
        "user_id": "budi@x.com",
        "max_budget_in_team": 100.0,
    }
    assert plan.unmanaged == () and plan.orphan_teams == ()


def test_in_sync_is_empty():
    want, have = world()
    plan = diff(want, have)
    assert plan == Plan(actions=(), unmanaged=(), orphan_teams=())
    assert plan.actions == ()


def test_team_budget_change_is_nondestructive_update():
    want, have = world()
    want = desired([team(max_budget=800.0)], list(want.members.values()))
    plan = diff(want, have)
    assert kinds(plan) == ["update_team"]
    act = plan.actions[0]
    assert act.target == "team:dev"
    assert act.destructive is False
    assert act.before["max_budget"] == 500.0 and act.after["max_budget"] == 800.0


def test_team_model_removed_is_destructive():
    want, have = world()
    want = desired(
        [team(models=("company-fast", "company-coding"))],
        list(want.members.values()),
        {u: policy(("company-fast", "company-coding")) for u in want.members},
    )
    plan = diff(want, have)
    team_action = by_kind(plan, "update_team")[0]
    assert team_action.destructive is True
    assert team_action.after["models"] == ["company-coding", "company-fast"]
    # Keys lose the model too, which is destructive as well.
    assert all(a.destructive for a in by_kind(plan, "update_key"))
    assert len(by_kind(plan, "update_key")) == 2


def test_team_model_added_is_not_destructive():
    want, have = world()
    have = actual(
        [team(models=("company-fast",))], have.members, have.keys
    )
    plan = diff(want, have)
    assert kinds(plan) == ["update_team"]
    assert plan.actions[0].destructive is False


def test_member_budget_change_updates_member():
    want, have = world()
    want = desired(
        [team()], [member("budi@x.com", budget=150.0), member("sari@x.com")]
    )
    plan = diff(want, have)
    assert kinds(plan) == ["update_member"]
    act = plan.actions[0]
    assert act.target == "member:dev/budi@x.com"
    assert act.destructive is False
    assert act.before["max_budget_in_team"] == 100.0
    assert act.after == {"team_id": "dev", "user_id": "budi@x.com", "max_budget_in_team": 150.0}


def test_removed_member_is_removed_and_keys_blocked():
    want, have = world()
    want = desired([team()], [member("sari@x.com")])
    plan = diff(want, have)
    assert kinds(plan) == ["block_key", "remove_member"]
    assert all(a.destructive for a in plan.actions)
    block, remove = plan.actions
    assert block.target == "key:budi@x.com-laptop"
    assert block.after is None
    assert block.before == {
        "token": "tok-budi@x.com-laptop-0000",
        "key_alias": "budi@x.com-laptop",
        "user_id": "budi@x.com",
        "team_id": "dev",
    }
    assert remove.target == "member:dev/budi@x.com"
    assert remove.after is None


def test_all_keys_of_removed_member_are_blocked():
    want, have = world()
    have = actual(
        [team()],
        have.members,
        list(have.keys) + [key("budi@x.com-ci", "budi@x.com")],
    )
    want = desired([team()], [member("sari@x.com")])
    plan = diff(want, have)
    assert [a.target for a in by_kind(plan, "block_key")] == [
        "key:budi@x.com-ci",
        "key:budi@x.com-laptop",
    ]


def test_member_moved_team_blocks_old_key():
    old, new = team("dev"), team("fin", models=("company-fast",))
    members_have = [member("budi@x.com", "dev")]
    have = actual([old, new], members_have, [key("budi@x.com-laptop", "budi@x.com", "dev")])
    want = desired([old, new], [member("budi@x.com", "fin")], {"budi@x.com": policy(("company-fast",))})
    plan = diff(want, have)
    assert kinds(plan) == ["add_member", "block_key", "remove_member"]
    assert [a.target for a in plan.actions] == [
        "member:fin/budi@x.com",
        "key:budi@x.com-laptop",
        "member:dev/budi@x.com",
    ]
    assert by_kind(plan, "add_member")[0].destructive is False
    assert by_kind(plan, "block_key")[0].destructive is True
    assert by_kind(plan, "remove_member")[0].destructive is True


def test_key_policy_drift_updates_key():
    want, have = world()
    drifted = key("budi@x.com-laptop", "budi@x.com", pol=policy(rpm=10, budgets=(BudgetWindow("24h", 1),)))
    have = actual([team()], have.members, [drifted, have.keys[1]])
    plan = diff(want, have)
    assert kinds(plan) == ["update_key"]
    act = plan.actions[0]
    assert act.target == "key:budi@x.com-laptop"
    assert act.destructive is False
    assert act.after == {
        "token": "tok-budi@x.com-laptop-0000",
        "models": sorted(ALL),
        "rpm_limit": 60,
        "budgets": [{"duration": "24h", "max_usd": 10}, {"duration": "30d", "max_usd": 100}],
    }
    assert act.before["rpm_limit"] == 10
    assert act.before["budgets"] == [{"duration": "24h", "max_usd": 1}]


def test_key_budget_order_is_not_drift():
    want, have = world()
    reordered = key("budi@x.com-laptop", "budi@x.com", pol=policy(budgets=tuple(reversed(BUDGETS))))
    have = actual([team()], have.members, [reordered, have.keys[1]])
    assert diff(want, have).actions == ()


def test_key_model_narrowed_is_destructive():
    want, have = world()
    wide = key("budi@x.com-laptop", "budi@x.com", pol=policy(ALL))
    want = desired(
        [team()],
        list(want.members.values()),
        {"budi@x.com": policy(("company-fast",)), "sari@x.com": policy()},
    )
    have = actual([team()], have.members, [wide, have.keys[1]])
    plan = diff(want, have)
    assert kinds(plan) == ["update_key"]
    assert plan.actions[0].destructive is True


def test_blocked_and_unmanaged_keys_untouched():
    want, have = world()
    extra = [
        key("legacy", "someone@x.com", managed=False),
        key("budi@x.com-old", "ghost@x.com", blocked=True),
        key("sari@x.com-stale", "sari@x.com", blocked=True, pol=policy(rpm=1)),
    ]
    have = actual([team()], have.members, list(have.keys) + extra)
    plan = diff(want, have)
    assert plan.actions == ()
    assert plan.unmanaged == ("key:legacy",)


def test_unmanaged_key_without_alias_uses_token_prefix():
    want, have = world()
    anon = ActualKey("abcdef1234567890", None, None, None, False, policy(), managed=False)
    have = actual([team()], have.members, list(have.keys) + [anon])
    assert diff(want, have).unmanaged == ("key:abcdef12",)


def test_unmanaged_team_listed_not_touched():
    want, have = world()
    have = actual(
        [team(), team("legacy-team")],
        have.members,
        have.keys,
        managed=["dev"],
    )
    plan = diff(want, have)
    assert plan.actions == ()
    assert plan.unmanaged == ("team:legacy-team",)
    assert plan.orphan_teams == ()


def test_desired_team_exists_unmanaged_raises_conflict():
    want, _ = world()
    have = actual([team()], [], [], managed=[])
    with pytest.raises(ConflictError) as exc:
        diff(want, have)
    assert "dev" in str(exc.value)


def test_orphan_team_without_prune_listed():
    want, have = world()
    ops = team("ops")
    ops_members = [member("old@x.com", "ops")]
    have = actual(
        [team(), ops],
        list(have.members) + ops_members,
        list(have.keys) + [key("old@x.com-laptop", "old@x.com", "ops")],
    )
    plan = diff(want, have)
    assert plan.orphan_teams == ("ops",)
    assert plan.actions == ()


def test_orphan_team_with_prune():
    want, have = world()
    ops = team("ops")
    have = actual(
        [team(), ops],
        list(have.members) + [member("old@x.com", "ops")],
        list(have.keys) + [key("old@x.com-laptop", "old@x.com", "ops")],
    )
    plan = diff(want, have, prune=True)
    assert kinds(plan) == ["block_key", "remove_member", "delete_team"]
    assert [a.target for a in plan.actions] == [
        "key:old@x.com-laptop",
        "member:ops/old@x.com",
        "team:ops",
    ]
    assert all(a.destructive for a in plan.actions)
    assert plan.orphan_teams == ("ops",)
    assert plan.actions[2].after is None


def test_orphan_team_does_not_hide_in_sync_state_of_others():
    want, have = world()
    have = actual([team(), team("ops")], have.members, have.keys)
    want = desired([team()], list(want.members.values()), dict(want.key_policies))
    plan = diff(want, have)
    assert plan.orphan_teams == ("ops",)
    assert plan.actions == ()


def test_actions_ordered_by_kind_then_target():
    members = [member("zed@x.com"), member("amy@x.com")]
    want = desired([team("b-team"), team("a-team")], [member("zed@x.com", "b-team"), member("amy@x.com", "a-team")])
    plan = diff(want, actual())
    assert [(a.kind, a.target) for a in plan.actions] == [
        ("create_team", "team:a-team"),
        ("create_team", "team:b-team"),
        ("add_member", "member:a-team/amy@x.com"),
        ("add_member", "member:b-team/zed@x.com"),
    ]
    assert members  # builders exercised


def test_diff_is_pure_and_deterministic():
    want, have = world()
    want = desired([team(max_budget=1.0)], [member("sari@x.com")])
    assert diff(want, have) == diff(want, have)


def test_action_is_frozen():
    act = Action("create_team", "team:x", None, {}, False)
    with pytest.raises(AttributeError):
        act.kind = "delete_team"  # type: ignore[misc]
