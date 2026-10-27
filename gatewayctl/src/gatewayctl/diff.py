"""Pure diff of desired vs actual gateway state into an ordered plan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, get_args

from gatewayctl.model import (
    ActualKey,
    ActualState,
    DesiredState,
    KeyPolicy,
    MemberSpec,
    TeamSpec,
)

ActionKind = Literal[
    "create_team",
    "update_team",
    "add_member",
    "update_member",
    "update_key",
    "block_key",
    "remove_member",
    "delete_team",
]

# Execution order: additions first, then reductions (access revoked before members/teams go).
_ORDER = {kind: i for i, kind in enumerate(get_args(ActionKind))}


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target: str
    before: Mapping | None
    after: Mapping | None
    destructive: bool


@dataclass(frozen=True)
class Plan:
    actions: tuple[Action, ...]
    unmanaged: tuple[str, ...]
    orphan_teams: tuple[str, ...]


class ConflictError(Exception):
    """A team in the file already exists in LiteLLM but is not managed by gatewayctl."""


def _team_dict(team: TeamSpec) -> dict:
    return {
        "team_id": team.team_id,
        "alias": team.alias,
        "models": sorted(team.models),
        "max_budget": team.max_budget,
        "budget_duration": team.budget_duration,
        "rpm_limit": team.rpm_limit,
    }


def _member_dict(member: MemberSpec) -> dict:
    return {
        "team_id": member.team_id,
        "user_id": member.user_id,
        "max_budget_in_team": member.max_budget_in_team,
    }


def _key_policy_dict(token: str, policy: KeyPolicy) -> dict:
    return {
        "token": token,
        "models": sorted(policy.models),
        "rpm_limit": policy.rpm_limit,
        "budgets": [{"duration": b.duration, "max_usd": b.max_usd} for b in policy.budgets],
    }


def _key_name(key: ActualKey) -> str:
    return key.key_alias or key.token[:8]


def _narrowed(before: Mapping, after: Mapping) -> bool:
    return bool(set(before["models"]) - set(after["models"]))


def _same_policy(a: KeyPolicy, b: KeyPolicy) -> bool:
    return (
        a.models == b.models
        and a.rpm_limit == b.rpm_limit
        and sorted((w.duration, w.max_usd) for w in a.budgets)
        == sorted((w.duration, w.max_usd) for w in b.budgets)
    )


def diff(desired: DesiredState, actual: ActualState, *, prune: bool = False) -> Plan:
    actions: list[Action] = []
    unmanaged: list[str] = []

    for team_id in sorted(actual.teams):
        if team_id in actual.managed_teams:
            continue
        if team_id in desired.teams:
            raise ConflictError(
                f"team '{team_id}' sudah ada di LiteLLM tetapi tidak dikelola gatewayctl; "
                "tidak diambil alih"
            )
        unmanaged.append(f"team:{team_id}")

    orphan_teams = sorted(
        t for t in actual.managed_teams if t in actual.teams and t not in desired.teams
    )
    orphans = frozenset(orphan_teams)

    # Teams
    for team_id, want in sorted(desired.teams.items()):
        have = actual.teams.get(team_id)
        after = _team_dict(want)
        if have is None:
            actions.append(Action("create_team", f"team:{team_id}", None, after, False))
        elif have != want:
            before = _team_dict(have)
            actions.append(
                Action("update_team", f"team:{team_id}", before, after, _narrowed(before, after))
            )

    # Members
    have_members = {(m.team_id, m.user_id): m for m in actual.members}
    for user_id, want in sorted(desired.members.items()):
        have = have_members.get((want.team_id, user_id))
        after = _member_dict(want)
        if have is None:
            actions.append(Action("add_member", f"member:{want.team_id}/{user_id}", None, after, False))
        elif have.max_budget_in_team != want.max_budget_in_team:
            actions.append(
                Action("update_member", f"member:{want.team_id}/{user_id}", _member_dict(have), after, False)
            )

    for (team_id, user_id), have in sorted(have_members.items()):
        want = desired.members.get(user_id)
        if want is not None and want.team_id == team_id:
            continue
        # Members of an orphan team stay untouched without prune, unless the user moved elsewhere.
        if team_id in orphans and not prune and want is None:
            continue
        actions.append(
            Action("remove_member", f"member:{team_id}/{user_id}", _member_dict(have), None, True)
        )

    # Keys
    for key in actual.keys:
        if not key.managed:
            unmanaged.append(f"key:{_key_name(key)}")
            continue
        if key.blocked:
            continue
        want = desired.members.get(key.user_id) if key.user_id is not None else None
        if want is None or want.team_id != key.team_id:
            if want is None and key.team_id in orphans and not prune:
                continue
            before = {
                "token": key.token,
                "key_alias": key.key_alias,
                "user_id": key.user_id,
                "team_id": key.team_id,
            }
            actions.append(Action("block_key", f"key:{_key_name(key)}", before, None, True))
            continue
        policy = desired.key_policies.get(want.user_id)
        if policy is None or _same_policy(key.policy, policy):
            continue
        before = _key_policy_dict(key.token, key.policy)
        after = _key_policy_dict(key.token, policy)
        actions.append(
            Action("update_key", f"key:{_key_name(key)}", before, after, _narrowed(before, after))
        )

    if prune:
        for team_id in orphan_teams:
            actions.append(
                Action("delete_team", f"team:{team_id}", _team_dict(actual.teams[team_id]), None, True)
            )

    actions.sort(key=lambda a: (_ORDER[a.kind], a.target))
    return Plan(tuple(actions), tuple(sorted(unmanaged)), tuple(orphan_teams))
