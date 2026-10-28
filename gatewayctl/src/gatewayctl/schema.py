"""Parse and validate entitlements.yaml into a DesiredState (spec 6.1, 6.2)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    ValidationError,
    model_validator,
)
from yaml.constructor import ConstructorError

from gatewayctl.model import (
    PROXY_ADMIN_USER_ID,
    BudgetWindow,
    DesiredState,
    KeyPolicy,
    MemberSpec,
    TeamSpec,
)

TEAM_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
DURATION_PATTERN = r"^\d+[hd]$"


class EntitlementsError(Exception):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


@dataclass(frozen=True)
class GatewayConfig:
    aliases: frozenset[str]
    fallbacks: Mapping[str, tuple[str, ...]]


def load_gateway_config(path: Path) -> GatewayConfig:
    """Read model aliases and router fallbacks from LiteLLM's config.yaml."""
    data = _read_yaml(path)
    where = str(path)

    model_list = data.get("model_list")
    if not isinstance(model_list, list) or not model_list:
        raise EntitlementsError(where, "model_list kosong atau tidak ada")
    aliases: set[str] = set()
    for i, entry in enumerate(model_list):
        name = entry.get("model_name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name:
            raise EntitlementsError(where, f"model_list[{i}].model_name wajib berupa teks")
        aliases.add(name)

    router = data.get("router_settings") or {}
    if not isinstance(router, dict):
        raise EntitlementsError(where, "router_settings harus berupa mapping")
    raw_fallbacks = router.get("fallbacks") or []
    if not isinstance(raw_fallbacks, list):
        raise EntitlementsError(where, "router_settings.fallbacks harus berupa list")
    fallbacks: dict[str, tuple[str, ...]] = {}
    for i, entry in enumerate(raw_fallbacks):
        if not isinstance(entry, dict):
            raise EntitlementsError(where, f"router_settings.fallbacks[{i}] harus berupa mapping")
        for source, targets in entry.items():
            if isinstance(targets, str):
                targets = [targets]
            if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
                raise EntitlementsError(
                    where, f"router_settings.fallbacks[{i}].{source} harus berupa list alias"
                )
            fallbacks[source] = fallbacks.get(source, ()) + tuple(targets)

    return GatewayConfig(aliases=frozenset(aliases), fallbacks=fallbacks)


def load_entitlements(path: Path, gateway: GatewayConfig) -> DesiredState:
    """Parse, validate (spec 6.2), and resolve an entitlements file."""
    data = _read_yaml(path)
    try:
        doc = _File.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise EntitlementsError(_join_loc(first["loc"]) or str(path), _message(first)) from None
    return _resolve(doc, gateway)


def _read_yaml(path: Path) -> dict[str, Any]:
    where = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EntitlementsError(where, f"file tidak dapat dibaca ({exc.strerror or exc})") from None
    except UnicodeDecodeError:
        raise EntitlementsError(where, "file bukan teks UTF-8; simpan ulang sebagai UTF-8") from None
    try:
        data = _safe_load_unique(text)
    except yaml.YAMLError as exc:
        raise EntitlementsError(where, f"YAML tidak valid: {_yaml_problem(exc)}") from None
    if not isinstance(data, dict):
        raise EntitlementsError(where, "isi file harus berupa mapping YAML")
    return data


_MERGE_TAG = "tag:yaml.org,2002:merge"


def _safe_load_unique(text: str) -> Any:
    """yaml.safe_load that rejects a repeated mapping key instead of keeping the last one."""
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        if node is None:
            return None
        _check_unique_keys(loader, node)
        return loader.construct_document(node)
    finally:
        loader.dispose()


def _check_unique_keys(loader: yaml.SafeLoader, root: yaml.Node) -> None:
    visited: set[int] = set()
    stack: list[tuple[yaml.Node, str]] = [(root, "")]
    while stack:
        node, path = stack.pop()
        # Aliases share nodes; visit each once (also guards recursive anchors).
        if id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, yaml.SequenceNode):
            stack.extend((child, f"{path}[{i}]") for i, child in enumerate(node.value))
            continue
        if not isinstance(node, yaml.MappingNode):
            continue
        first_line: dict[Any, int] = {}
        for key_node, value_node in node.value:
            if key_node.tag == _MERGE_TAG:
                # `<<: *anchor` followed by an explicit key is an override, not a duplicate.
                stack.append((value_node, path))
                continue
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            key = loader.construct_object(key_node)
            if not isinstance(key, Hashable):
                continue
            if key in first_line:
                where = f" di {path}" if path else ""
                raise ConstructorError(
                    problem=(
                        f"kunci duplikat '{key}'{where}, "
                        f"pertama ditulis di baris {first_line[key] + 1}"
                    ),
                    problem_mark=key_node.start_mark,
                )
            first_line[key] = key_node.start_mark.line
            stack.append((value_node, f"{path}.{key}" if path else str(key)))


def _yaml_problem(exc: yaml.YAMLError) -> str:
    problem = getattr(exc, "problem", None)
    mark = getattr(exc, "problem_mark", None)
    if problem and mark is not None:
        return f"{problem} (baris {mark.line + 1}, kolom {mark.column + 1})"
    return " ".join(str(exc).split())


# --- pydantic file model ---------------------------------------------------


def normalize_id(value: str) -> str:
    """Canonical user_id or service account name; the CLI uses it for --user too."""
    return value.strip().lower()


def _normalize_id_input(value: Any) -> Any:
    return normalize_id(value) if isinstance(value, str) else value


def _id_problem(value: str) -> str | None:
    if not value:
        return "tidak boleh kosong"
    # Cf covers zero-width characters that str.strip() and isspace() miss.
    if any(ch.isspace() or unicodedata.category(ch) == "Cf" for ch in value):
        return f"id {value!r} tidak boleh mengandung spasi atau karakter tak terlihat"
    if value == PROXY_ADMIN_USER_ID:
        return f"id {value!r} dipakai LiteLLM untuk master key dan tidak bisa dikelola"
    return None


def _valid_id(value: str) -> str:
    problem = _id_problem(value)
    if problem:
        raise ValueError(problem)
    return value


def _non_empty(value: str) -> str:
    if not value:
        raise ValueError("tidak boleh kosong")
    return value


def _team_id(value: str) -> str:
    if not re.fullmatch(TEAM_ID_PATTERN, value, re.ASCII):
        raise ValueError(f"id team '{value}' tidak valid; harus cocok dengan pola {TEAM_ID_PATTERN}")
    return value


def _duration(value: str) -> str:
    if not re.fullmatch(DURATION_PATTERN, value, re.ASCII):
        raise ValueError(
            f"durasi '{value}' tidak valid; harus cocok dengan pola {DURATION_PATTERN}, "
            "misalnya 24h atau 30d"
        )
    if _duration_hours(value) == 0:
        raise ValueError(f"durasi '{value}' harus lebih dari 0")
    return value


def _duration_hours(value: str) -> int:
    return int(value[:-1]) * (24 if value.endswith("d") else 1)


def _exactly_int(value: Any) -> Any:
    # Literal[1] alone also accepts true and 1.0.
    if type(value) is not int:
        raise ValueError("harus bernilai 1")
    return value


def _require_string_keys(data: Any) -> None:
    if isinstance(data, dict):
        for key in data:
            if not isinstance(key, str):
                raise ValueError(
                    f"kunci {key!r} bukan teks (YAML membacanya sebagai "
                    f"{type(key).__name__}); beri tanda kutip"
                )


def _none_as_empty_list(value: Any) -> Any:
    return [] if value is None else value


def _string_keyed_dict(value: Any) -> Any:
    if value is None:
        return {}
    _require_string_keys(value)
    return value


UserId = Annotated[str, BeforeValidator(_normalize_id_input), AfterValidator(_valid_id)]
TeamId = Annotated[str, AfterValidator(_team_id)]
Duration = Annotated[str, AfterValidator(_duration)]
# Strict: YAML true/yes and quoted numbers must not become 1 or a number silently.
Usd = Annotated[float, Strict(), Field(ge=0, allow_inf_nan=False)]
Rpm = Annotated[int, Strict(), Field(gt=0)]
Aliases = Annotated[list[str], Field(min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _string_keys(cls, data: Any) -> Any:
        _require_string_keys(data)
        return data


class _Budget(_Strict):
    duration: Duration
    max_usd: Usd


Budgets = Annotated[list[_Budget], BeforeValidator(_none_as_empty_list)]


class _Key(_Strict):
    # None means "not set": a member override then inherits member_defaults.key,
    # so a null (e.g. commented-out list items) never drops a limit. [] clears budgets.
    models: Aliases | None = None
    rpm_limit: Rpm | None = None
    budgets: list[_Budget] | None = None


class _MemberDefaults(_Strict):
    max_budget_in_team: Usd | None = None
    key: _Key = Field(default_factory=_Key)


class _Member(_Strict):
    user_id: UserId
    max_budget_in_team: Usd | None = None
    key: _Key | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"user_id": data}
        if not isinstance(data, dict):
            raise ValueError("member harus berupa user_id (teks) atau mapping dengan user_id")
        return data


class _TeamBudget(_Strict):
    max_usd: Usd
    duration: Duration


class _Team(_Strict):
    alias: Annotated[str, AfterValidator(_non_empty)] | None = None
    models: Aliases
    budget: _TeamBudget
    rpm_limit: Rpm
    member_defaults: _MemberDefaults = Field(default_factory=_MemberDefaults)
    members: Annotated[list[_Member], BeforeValidator(_none_as_empty_list)] = Field(
        default_factory=list
    )


class _ServiceAccount(_Strict):
    team: str
    models: Aliases | None = None
    rpm_limit: Rpm | None = None
    budgets: Budgets = Field(default_factory=list)


class _File(_Strict):
    version: Annotated[Literal[1], BeforeValidator(_exactly_int)]
    teams: Annotated[dict[TeamId, _Team], BeforeValidator(_string_keyed_dict)] = Field(
        default_factory=dict
    )
    service_accounts: Annotated[
        dict[str, _ServiceAccount], BeforeValidator(_string_keyed_dict)
    ] = Field(default_factory=dict)


_MESSAGES = {
    "missing": "wajib diisi",
    "extra_forbidden": "field tidak dikenal",
    "string_type": "harus berupa teks",
    "int_type": "harus berupa bilangan bulat",
    "int_parsing": "harus berupa bilangan bulat",
    "int_from_float": "harus berupa bilangan bulat",
    "float_type": "harus berupa angka",
    "float_parsing": "harus berupa angka",
    "finite_number": "harus berupa angka terhingga",
    "list_type": "harus berupa list",
    "dict_type": "harus berupa mapping",
    "model_type": "harus berupa mapping",
    "too_short": "tidak boleh kosong",
}


def _message(error: Mapping[str, Any]) -> str:
    kind = error["type"]
    ctx = error.get("ctx") or {}
    if kind == "value_error":
        return str(ctx["error"])
    if kind == "greater_than":
        return f"harus lebih besar dari {ctx['gt']}"
    if kind == "greater_than_equal":
        return f"tidak boleh kurang dari {ctx['ge']}"
    if kind == "literal_error":
        return f"harus bernilai {ctx['expected']}"
    return _MESSAGES.get(kind) or f"nilai tidak valid ({error['msg']})"


def _join_loc(loc: tuple[int | str, ...]) -> str:
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        elif part != "[key]":
            path += f".{part}" if path else str(part)
    return path


# --- cross-field validation and resolution ----------------------------------


def _resolve(doc: _File, gateway: GatewayConfig) -> DesiredState:
    teams: dict[str, TeamSpec] = {}
    members: dict[str, MemberSpec] = {}
    policies: dict[str, KeyPolicy] = {}

    for team_id, team in doc.teams.items():
        base = f"teams.{team_id}"
        for i, alias in enumerate(team.models):
            if alias not in gateway.aliases:
                raise EntitlementsError(
                    f"{base}.models[{i}]", f"alias '{alias}' tidak ada di config.yaml"
                )
        team_models = frozenset(team.models)
        for source in team.models:
            for target in gateway.fallbacks.get(source, ()):
                if target not in team_models:
                    raise EntitlementsError(
                        f"{base}.models",
                        f"alias '{source}' memiliki fallback ke '{target}', "
                        f"tetapi '{target}' tidak ada di models team",
                    )
        teams[team_id] = TeamSpec(
            team_id=team_id,
            alias=team.alias or team_id,
            models=team_models,
            max_budget=team.budget.max_usd,
            budget_duration=team.budget.duration,
            rpm_limit=team.rpm_limit,
        )

        defaults = team.member_defaults
        _check_subset(defaults.key.models, team_models, f"{base}.member_defaults.key.models", team_id)
        _check_budgets(defaults.key.budgets, f"{base}.member_defaults.key.budgets")
        for i, member in enumerate(team.members):
            path = f"{base}.members[{i}]"
            user_id = member.user_id
            if user_id in members:
                raise EntitlementsError(
                    path, f"user '{user_id}' sudah terdaftar di team '{members[user_id].team_id}'"
                )
            key = defaults.key
            if member.key is not None:
                _check_subset(member.key.models, team_models, f"{path}.key.models", team_id)
                _check_budgets(member.key.budgets, f"{path}.key.budgets")
                # Null fields inherit the defaults (see _Key).
                key = key.model_copy(
                    update={name: value for name, value in member.key if value is not None}
                )
            if member.max_budget_in_team is not None:
                budget_in_team = member.max_budget_in_team
            else:
                budget_in_team = defaults.max_budget_in_team
            members[user_id] = MemberSpec(user_id, team_id, budget_in_team)
            policies[user_id] = _policy(key.models, key.rpm_limit, key.budgets, team_models)

    for name, account in doc.service_accounts.items():
        path = f"service_accounts.{name}"
        account_id = normalize_id(name)
        problem = _id_problem(account_id)
        if problem:
            raise EntitlementsError(path, f"nama service account {problem}")
        if account_id in members:
            other = members[account_id]
            if other.kind == "user":
                message = f"nama service account bentrok dengan user di team '{other.team_id}'"
            else:
                message = f"service account '{account_id}' sudah didefinisikan"
            raise EntitlementsError(path, message)
        if account.team not in teams:
            raise EntitlementsError(f"{path}.team", f"team '{account.team}' tidak ada di file")
        team_models = teams[account.team].models
        _check_subset(account.models, team_models, f"{path}.models", account.team)
        _check_budgets(account.budgets, f"{path}.budgets")
        members[account_id] = MemberSpec(account_id, account.team, None, "service_account")
        policies[account_id] = _policy(
            account.models, account.rpm_limit, account.budgets, team_models
        )

    return DesiredState(teams=teams, members=members, key_policies=policies)


def _check_subset(
    models: list[str] | None, team_models: frozenset[str], path: str, team_id: str
) -> None:
    if models is None:
        return
    outside = [m for m in models if m not in team_models]
    if outside:
        listed = ", ".join(f"'{m}'" for m in outside)
        raise EntitlementsError(path, f"model {listed} tidak termasuk models team '{team_id}'")


def _check_budgets(budgets: list[_Budget] | None, path: str) -> None:
    """One key must not carry two windows of the same length (24h and 1d count as equal)."""
    first: dict[int, int] = {}
    for i, budget in enumerate(budgets or ()):
        hours = _duration_hours(budget.duration)
        if hours in first:
            raise EntitlementsError(
                f"{path}[{i}].duration",
                f"durasi '{budget.duration}' sama dengan {path}[{first[hours]}]; "
                "satu key hanya boleh punya satu budget per durasi",
            )
        first[hours] = i


def _policy(
    models: list[str] | None,
    rpm_limit: int | None,
    budgets: list[_Budget] | None,
    team_models: frozenset[str],
) -> KeyPolicy:
    return KeyPolicy(
        models=frozenset(models) if models is not None else team_models,
        rpm_limit=rpm_limit,
        budgets=tuple(BudgetWindow(b.duration, b.max_usd) for b in budgets or ()),
    )
