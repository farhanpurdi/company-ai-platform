"""Run a Plan against LiteLLM, one action at a time, auditing each success."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from gatewayctl.audit import AuditLog
from gatewayctl.client import LiteLLMClient
from gatewayctl.diff import Action, Plan
from gatewayctl.state import MANAGED_BY

MANAGED_METADATA = {"managed_by": MANAGED_BY}


class ApplyError(Exception):
    def __init__(self, done: int, action: Action, cause: Exception) -> None:
        super().__init__(f"aksi {action.kind} {action.target} gagal setelah {done} aksi berhasil: {cause}")
        self.done = done
        self.action = action
        self.cause = cause


class AuditWriteError(Exception):
    """An action was applied in LiteLLM but its audit line could not be written."""

    def __init__(self, done: int, action: Action, cause: OSError) -> None:
        super().__init__(f"aksi {action.kind} {action.target} diterapkan tetapi audit gagal ditulis: {cause}")
        self.done = done
        self.action = action
        self.cause = cause


def budget_limits(budgets: Iterable[Mapping]) -> list[dict]:
    # Single place that maps gatewayctl budget windows to LiteLLM's budget_limits fields.
    return [{"budget_duration": b["duration"], "max_budget": b["max_usd"]} for b in budgets]


def _team_payload(after: Mapping) -> dict:
    return {
        "team_id": after["team_id"],
        "team_alias": after["alias"],
        "models": list(after["models"]),
        "max_budget": after["max_budget"],
        "budget_duration": after["budget_duration"],
        "rpm_limit": after["rpm_limit"],
        "metadata": dict(MANAGED_METADATA),
    }


def _call(action: Action, client: LiteLLMClient) -> None:
    before, after = action.before, action.after
    match action.kind:
        case "create_team":
            client.team_new(_team_payload(after))
        case "update_team":
            client.team_update(_team_payload(after))
        case "add_member":
            client.member_add(after["team_id"], after["user_id"], after["max_budget_in_team"])
        case "update_member":
            client.member_update(after["team_id"], after["user_id"], after["max_budget_in_team"])
        case "update_key":
            client.key_update(
                {
                    "key": after["token"],
                    "models": list(after["models"]),
                    "rpm_limit": after["rpm_limit"],
                    "budget_limits": budget_limits(after["budgets"]),
                    "metadata": dict(MANAGED_METADATA),
                }
            )
        case "block_key":
            client.key_block(before["token"])
        case "remove_member":
            client.member_delete(before["team_id"], before["user_id"])
        case "delete_team":
            client.team_delete(before["team_id"])
        case other:
            raise ValueError(f"aksi tidak dikenal: {other}")


def execute(plan: Plan, client: LiteLLMClient, audit: AuditLog) -> int:
    """Apply actions in order; stop at the first failure. Returns the number applied."""
    done = 0
    for action in plan.actions:
        try:
            _call(action, client)
        except Exception as exc:
            raise ApplyError(done, action, exc) from exc
        try:
            audit.record(action.kind, action.target, action.before, action.after)
        except OSError as exc:
            raise AuditWriteError(done, action, exc) from exc
        done += 1
    return done
