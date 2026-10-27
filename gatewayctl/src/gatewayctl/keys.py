"""Key lifecycle: issue, block, list. Raw keys are returned, never recorded."""

from __future__ import annotations

import hashlib

from gatewayctl.apply import MANAGED_METADATA
from gatewayctl.audit import AuditLog
from gatewayctl.client import LiteLLMClient
from gatewayctl.model import ActualKey, ActualState, DesiredState


class BlockError(Exception):
    """Blocking stopped at one key; `blocked` keys before it were blocked and audited.

    `applied` is True when that key itself was blocked but its audit line failed.
    """

    def __init__(self, blocked: list[str], target: str, cause: Exception, *, applied: bool) -> None:
        super().__init__(f"pemblokiran {target} gagal setelah {len(blocked)} key: {cause}")
        self.blocked = blocked
        self.target = target
        self.cause = cause
        self.applied = applied


def _name(key: ActualKey) -> str:
    return key.key_alias or key.token[:8]


def issue_key(
    desired: DesiredState,
    actual: ActualState,
    client: LiteLLMClient,
    audit: AuditLog,
    owner: str,
    label: str,
) -> str:
    member = desired.members.get(owner)
    policy = desired.key_policies.get(owner)
    if member is None or policy is None:
        raise ValueError(f"'{owner}' tidak terdaftar di file entitlements")
    alias = f"{owner}-{label}"
    if any(k.key_alias == alias for k in actual.keys):
        raise ValueError(f"alias key '{alias}' sudah dipakai; pilih label lain")
    result = client.key_generate(
        {
            "user_id": owner,
            "team_id": member.team_id,
            "key_alias": alias,
            "models": sorted(policy.models),
            "rpm_limit": policy.rpm_limit,
            "budget_limits": [
                {"budget_duration": b.duration, "max_budget": b.max_usd} for b in policy.budgets
            ],
            "metadata": {**MANAGED_METADATA, "owner_kind": member.kind},
        }
    )
    raw = result["key"]
    token = result.get("token_id") or result.get("token")
    if not token or token == raw or str(token).startswith("sk-"):
        # Never let a raw key reach the audit file, even if the API echoes it as the token.
        token = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    audit.record(
        "issue_key",
        f"key:{alias}",
        None,
        {"token": token, "user_id": owner, "team_id": member.team_id, "key_alias": alias},
    )
    return raw


def block_keys(
    actual: ActualState,
    client: LiteLLMClient,
    audit: AuditLog,
    *,
    user_id: str | None = None,
    alias: str | None = None,
) -> list[str]:
    if (user_id is None) == (alias is None):
        raise ValueError("pilih tepat satu dari user_id atau alias")
    blocked: list[str] = []
    for key in actual.keys:
        if key.blocked:
            continue
        if user_id is not None and key.user_id != user_id:
            continue
        if alias is not None and key.key_alias != alias:
            continue
        target = f"key:{_name(key)}"
        try:
            client.key_block(key.token)
        except Exception as exc:
            raise BlockError(blocked, target, exc, applied=False) from exc
        try:
            audit.record(
                "block_key",
                target,
                {
                    "token": key.token,
                    "key_alias": key.key_alias,
                    "user_id": key.user_id,
                    "team_id": key.team_id,
                },
                None,
            )
        except OSError as exc:
            raise BlockError(blocked, target, exc, applied=True) from exc
        blocked.append(key.token)
    return blocked


def key_rows(
    actual: ActualState, *, user_id: str | None = None, team_id: str | None = None
) -> list[dict]:
    rows = [
        {
            "key_alias": k.key_alias,
            "user_id": k.user_id,
            "team_id": k.team_id,
            "blocked": k.blocked,
            "spend": k.spend,
        }
        for k in actual.keys
        if (user_id is None or k.user_id == user_id) and (team_id is None or k.team_id == team_id)
    ]
    return sorted(rows, key=lambda r: (r["key_alias"] or "", r["user_id"] or ""))
