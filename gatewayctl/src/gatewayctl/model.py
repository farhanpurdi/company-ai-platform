"""Desired and actual gateway state shared by schema, state, and diff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

# LiteLLM's user_id for requests made with the master key. LiteLLM adds it as admin to
# every team gatewayctl creates, so it is never a managed member.
PROXY_ADMIN_USER_ID = "default_user_id"


@dataclass(frozen=True)
class BudgetWindow:
    duration: str
    max_usd: float


@dataclass(frozen=True)
class KeyPolicy:
    models: frozenset[str]
    rpm_limit: int | None
    budgets: tuple[BudgetWindow, ...]


@dataclass(frozen=True)
class TeamSpec:
    team_id: str
    alias: str
    models: frozenset[str]
    max_budget: float
    budget_duration: str
    rpm_limit: int


@dataclass(frozen=True)
class MemberSpec:
    user_id: str
    team_id: str
    max_budget_in_team: float | None
    kind: Literal["user", "service_account"] = "user"


@dataclass(frozen=True)
class DesiredState:
    teams: Mapping[str, TeamSpec]
    # Both keyed by user_id or service account name.
    members: Mapping[str, MemberSpec]
    key_policies: Mapping[str, KeyPolicy]


@dataclass(frozen=True)
class ActualKey:
    token: str
    key_alias: str | None
    user_id: str | None
    team_id: str | None
    blocked: bool
    policy: KeyPolicy
    managed: bool
    spend: float = 0.0


@dataclass(frozen=True)
class ActualState:
    teams: Mapping[str, TeamSpec]
    managed_teams: frozenset[str]
    # Members of managed teams only.
    members: tuple[MemberSpec, ...]
    keys: tuple[ActualKey, ...]
