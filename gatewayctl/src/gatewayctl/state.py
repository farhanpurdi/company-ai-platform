"""Fetch the current LiteLLM state as the same model the desired state uses."""

from __future__ import annotations

from gatewayctl.client import LiteLLMClient
from gatewayctl.model import (
    PROXY_ADMIN_USER_ID,
    ActualKey,
    ActualState,
    BudgetWindow,
    KeyPolicy,
    MemberSpec,
    TeamSpec,
)

MANAGED_BY = "gatewayctl"


def _is_managed(obj: dict) -> bool:
    return (obj.get("metadata") or {}).get("managed_by") == MANAGED_BY


def team_spec_from_api(team: dict) -> TeamSpec:
    # LiteLLM stores "unlimited" as null; map to neutral values so any desired limit differs.
    return TeamSpec(
        team_id=team["team_id"],
        alias=team.get("team_alias") or "",
        models=frozenset(team.get("models") or ()),
        max_budget=float(team.get("max_budget") or 0.0),
        budget_duration=team.get("budget_duration") or "",
        rpm_limit=int(team.get("rpm_limit") or 0),
    )


def key_from_api(key: dict) -> ActualKey:
    budgets = tuple(
        BudgetWindow(b["budget_duration"], b["max_budget"]) for b in key.get("budget_limits") or ()
    )
    return ActualKey(
        token=key["token"],
        key_alias=key.get("key_alias"),
        user_id=key.get("user_id"),
        team_id=key.get("team_id"),
        blocked=bool(key.get("blocked")),
        policy=KeyPolicy(
            models=frozenset(key.get("models") or ()),
            rpm_limit=key.get("rpm_limit"),
            budgets=budgets,
        ),
        managed=_is_managed(key),
        spend=float(key.get("spend") or 0.0),
    )


def _members_from_info(team_id: str, info: dict) -> list[MemberSpec]:
    # Budgets come from team_memberships, but some LiteLLM versions only create that row when a
    # member budget is set, so members_with_roles is the authoritative member list.
    budgets: dict[str, float | None] = {}
    for membership in info.get("team_memberships") or ():
        budget = (membership.get("litellm_budget_table") or {}).get("max_budget")
        budgets[membership["user_id"]] = None if budget is None else float(budget)
    for member in (info.get("team_info") or {}).get("members_with_roles") or ():
        user_id = member.get("user_id")
        if user_id:
            budgets.setdefault(user_id, None)
    budgets.pop(PROXY_ADMIN_USER_ID, None)
    return [
        MemberSpec(user_id=user_id, team_id=team_id, max_budget_in_team=budget)
        for user_id, budget in budgets.items()
    ]


def fetch_actual(client: LiteLLMClient) -> ActualState:
    teams: dict[str, TeamSpec] = {}
    managed: set[str] = set()
    members: list[MemberSpec] = []
    for team in client.list_teams():
        spec = team_spec_from_api(team)
        teams[spec.team_id] = spec
        if _is_managed(team):
            managed.add(spec.team_id)
            members.extend(_members_from_info(spec.team_id, client.team_info(spec.team_id)))
    keys = tuple(key_from_api(k) for k in client.list_keys())
    return ActualState(
        teams=teams,
        managed_teams=frozenset(managed),
        members=tuple(members),
        keys=keys,
    )
