"""Typer CLI. The only place that turns exceptions into exit codes (spec 6.7)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import typer

from gatewayctl.apply import ApplyError, AuditWriteError, execute
from gatewayctl.audit import AuditLog
from gatewayctl.client import ApiError, GatewayUnavailable, LiteLLMClient, redact
from gatewayctl.diff import ConflictError, Plan, diff
from gatewayctl.keys import BlockError, block_keys, issue_key, key_rows
from gatewayctl.model import ActualState, DesiredState
from gatewayctl.schema import EntitlementsError, load_entitlements, load_gateway_config, normalize_id
from gatewayctl.state import fetch_actual

EXIT_FAILED = 1
EXIT_CHANGES = 2
EXIT_UNAVAILABLE = 3
EXIT_NEEDS_CONFIRM = 4

DEFAULT_CONFIG = "deploy/litellm/config.yaml"
DEFAULT_BASE_URL = "http://litellm-a:4000"
DEFAULT_AUDIT_LOG = "var/audit.log"

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Provisioning deklaratif dan siklus hidup key untuk gateway LiteLLM.",
)
key_app = typer.Typer(no_args_is_help=True, help="Operasi key: issue, block, list.")
app.add_typer(key_app, name="key")


@dataclass
class Settings:
    file: Path | None
    config: Path
    base_url: str


def make_client(base_url: str, master_key: str) -> LiteLLMClient:
    return LiteLLMClient(base_url, master_key)


def say(message: str = "") -> None:
    typer.echo(message, err=True)


def fail(message: str, code: int = EXIT_FAILED) -> NoReturn:
    say(" ".join(message.split()))
    raise typer.Exit(code)


@app.callback()
def main(
    ctx: typer.Context,
    file: Path | None = typer.Option(
        None, "--file", envvar="GATEWAYCTL_FILE", help="Path entitlements.yaml."
    ),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Path config.yaml LiteLLM."),
    base_url: str = typer.Option(
        DEFAULT_BASE_URL, "--base-url", envvar="LITELLM_BASE_URL", help="URL LiteLLM."
    ),
) -> None:
    ctx.obj = Settings(file=file, config=config, base_url=base_url)


def _load_desired(settings: Settings) -> DesiredState:
    if settings.file is None:
        fail("--file (atau GATEWAYCTL_FILE) wajib diisi")
    try:
        gateway = load_gateway_config(settings.config)
        return load_entitlements(settings.file, gateway)
    except EntitlementsError as exc:
        fail(str(exc))


def _require_operator() -> str:
    operator = os.environ.get("GATEWAYCTL_OPERATOR", "").strip()
    if not operator:
        fail("GATEWAYCTL_OPERATOR wajib diisi untuk perintah ini")
    return operator


def _audit(operator: str) -> AuditLog:
    """Build the audit log and prove it is writable before any mutating call."""
    path = os.environ.get("GATEWAYCTL_AUDIT_LOG") or DEFAULT_AUDIT_LOG
    audit = AuditLog(Path(path), operator, os.environ.get("GATEWAYCTL_GIT_SHA") or "unknown")
    try:
        audit.ensure_writable()
    except OSError as exc:
        fail(f"audit log tidak dapat ditulis ({audit.path}): {exc.strerror or type(exc).__name__}")
    return audit


def _block_failed(audit: AuditLog, exc: BlockError) -> NoReturn:
    cause = exc.cause
    done = f"{len(exc.blocked)} key sebelumnya sudah diblokir dan tercatat di audit"
    if exc.applied:
        reason = cause.strerror if isinstance(cause, OSError) else None
        fail(
            f"{exc.target} sudah diblokir di LiteLLM tetapi audit log gagal ditulis ({audit.path}): "
            f"{reason or type(cause).__name__}. {done}."
        )
    if isinstance(cause, GatewayUnavailable):
        if not exc.blocked and not cause.may_have_applied:
            fail(str(cause), EXIT_UNAVAILABLE)
        fail(
            f"{cause} saat memblokir {exc.target}; key itu mungkin sudah diblokir. "
            f"{done}. Jalankan perintah lagi lalu periksa dengan gatewayctl key list."
        )
    detail = f"LiteLLM menolak permintaan: {cause}" if isinstance(cause, ApiError) else str(cause)
    fail(f"Gagal memblokir {exc.target}: {detail}. {done}. Jalankan perintah lagi setelah diperbaiki.")


def _master_key() -> str:
    master_key = os.environ.get("LITELLM_MASTER_KEY", "").strip()
    if not master_key:
        fail("LITELLM_MASTER_KEY kosong atau belum diatur", EXIT_UNAVAILABLE)
    return master_key


def _connect(settings: Settings, master_key: str):
    try:
        client = make_client(settings.base_url, master_key)
        client.check()
    except GatewayUnavailable as exc:
        fail(str(exc), EXIT_UNAVAILABLE)
    except ApiError as exc:
        # Body is left out on purpose: a proxy error page can be long and multi-line.
        if exc.status >= 500:
            fail(f"LiteLLM belum siap (HTTP {exc.status} pada {exc.path})", EXIT_UNAVAILABLE)
        fail(f"LiteLLM menolak permintaan (HTTP {exc.status} pada {exc.path})")
    return client


def _fetch(client) -> ActualState:
    try:
        return fetch_actual(client)
    except GatewayUnavailable as exc:
        fail(str(exc), EXIT_UNAVAILABLE)
    except ApiError as exc:
        fail(f"LiteLLM menolak permintaan: {exc}")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        fail(f"respons LiteLLM tidak sesuai format yang diharapkan ({type(exc).__name__})")


def _connect_and_fetch(settings: Settings, master_key: str):
    client = _connect(settings, master_key)
    return client, _fetch(client)


def _plan(desired: DesiredState, actual: ActualState, prune: bool) -> Plan:
    try:
        return diff(desired, actual, prune=prune)
    except ConflictError as exc:
        fail(str(exc))


_SYMBOL = {
    "create_team": "+",
    "add_member": "+",
    "update_team": "~",
    "update_member": "~",
    "update_key": "~",
    "block_key": "-",
    "remove_member": "-",
    "delete_team": "-",
}


def _print_plan(plan: Plan) -> None:
    for action in plan.actions:
        suffix = " [destructive]" if action.destructive else ""
        say(f"{_SYMBOL[action.kind]} {action.kind} {action.target}{suffix}")
    if plan.unmanaged:
        say("Unmanaged (tidak dikelola gatewayctl, tidak disentuh):")
        for target in plan.unmanaged:
            say(f"  {target}")
    if plan.orphan_teams:
        say("Team yatim (ada di LiteLLM, tidak ada di file; proses dengan --prune):")
        for team_id in plan.orphan_teams:
            say(f"  team:{team_id}")
    if plan.unmanaged_active_revoked:
        say(
            "PERINGATAN: key unmanaged milik member/team yang dicabut tetap aktif "
            "(tidak diblokir otomatis); blokir dengan: gatewayctl key block --alias <alias>"
        )
        for target in plan.unmanaged_active_revoked:
            say(f"  {target}")
    destructive = sum(1 for a in plan.actions if a.destructive)
    say(
        f"Ringkasan: {len(plan.actions)} aksi ({destructive} destruktif), "
        f"{len(plan.unmanaged)} unmanaged, {len(plan.orphan_teams)} team yatim"
    )


def _plan_json(plan: Plan) -> str:
    return json.dumps(
        {
            "actions": [
                {
                    "kind": a.kind,
                    "target": a.target,
                    "before": a.before,
                    "after": a.after,
                    "destructive": a.destructive,
                }
                for a in plan.actions
            ],
            "unmanaged": list(plan.unmanaged),
            "orphan_teams": list(plan.orphan_teams),
            "unmanaged_active_revoked": list(plan.unmanaged_active_revoked),
        },
        indent=2,
    )


@app.command("plan")
def plan_command(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Keluaran JSON."),
    prune: bool = typer.Option(False, "--prune", help="Sertakan penghapusan team yatim."),
) -> None:
    """Tampilkan selisih file dengan kondisi LiteLLM. Exit 0 sama, 2 ada perubahan."""
    settings: Settings = ctx.obj
    desired = _load_desired(settings)
    master_key = _master_key()
    client, actual = _connect_and_fetch(settings, master_key)
    plan = _plan(desired, actual, prune)
    if as_json:
        say(_plan_json(plan))
    else:
        _print_plan(plan)
    raise typer.Exit(EXIT_CHANGES if plan.actions else 0)


@app.command("apply")
def apply_command(
    ctx: typer.Context,
    confirm: bool = typer.Option(False, "--confirm", help="Izinkan aksi destruktif."),
    prune: bool = typer.Option(False, "--prune", help="Hapus team yatim."),
) -> None:
    """Terapkan selisih file ke LiteLLM."""
    settings: Settings = ctx.obj
    desired = _load_desired(settings)
    operator = _require_operator()
    master_key = _master_key()
    client, actual = _connect_and_fetch(settings, master_key)
    plan = _plan(desired, actual, prune)
    if not plan.actions:
        say("Tidak ada perubahan.")
        return
    _print_plan(plan)
    if any(a.destructive for a in plan.actions) and not confirm:
        fail("Ada aksi destruktif; tidak ada yang dijalankan. Ulangi dengan --confirm.", EXIT_NEEDS_CONFIRM)
    audit = _audit(operator)
    try:
        done = execute(plan, client, audit)
    except AuditWriteError as exc:
        fail(
            f"{exc.action.kind} {exc.action.target} sudah diterapkan di LiteLLM tetapi audit log gagal "
            f"ditulis ({audit.path}): {exc.cause.strerror or type(exc.cause).__name__}. "
            f"{exc.done} aksi sebelumnya tercatat di audit; catat aksi ini secara manual."
        )
    except ApplyError as exc:
        cause = redact(str(exc.cause), [master_key])
        if isinstance(exc.cause, GatewayUnavailable):
            if exc.cause.may_have_applied:
                fail(
                    f"{cause} pada {exc.action.kind} {exc.action.target}; aksi ini mungkin sudah diterapkan "
                    f"di LiteLLM tanpa catatan audit. {exc.done} aksi sebelumnya tercatat di audit; "
                    f"jalankan plan untuk memeriksa lalu catat aksi ini secara manual bila sudah diterapkan."
                )
            if exc.done == 0:
                fail(cause, EXIT_UNAVAILABLE)
        fail(
            f"Gagal pada {exc.action.kind} {exc.action.target}: {cause}. "
            f"{exc.done} aksi sebelumnya berhasil dan tercatat di audit; jalankan apply lagi setelah diperbaiki."
        )
    say(f"Selesai: {done} aksi diterapkan.")


@key_app.command("issue")
def key_issue(
    ctx: typer.Context,
    user: str | None = typer.Option(None, "--user", help="user_id atau nama service account."),
    label: str | None = typer.Option(None, "--label", help="Label key, mis. opencode."),
) -> None:
    """Terbitkan key; key mentah dicetak sekali ke stdout."""
    settings: Settings = ctx.obj
    user = (user or "").strip()
    label = (label or "").strip()
    if not user or not label:
        fail("--user dan --label wajib diisi")
    if any(c.isspace() for c in label):
        fail("--label tidak boleh berisi spasi")
    desired = _load_desired(settings)
    operator = _require_operator()
    master_key = _master_key()
    client, actual = _connect_and_fetch(settings, master_key)
    owner = normalize_id(user)
    alias = f"{owner}-{label}"
    audit = _audit(operator)
    try:
        raw = issue_key(desired, actual, client, audit, owner, label)
    except ValueError as exc:
        fail(str(exc))
    except OSError as exc:
        fail(
            f"key '{alias}' sudah dibuat di LiteLLM tetapi audit log gagal ditulis "
            f"({exc.strerror or type(exc).__name__}); key mentah tidak ditampilkan, "
            f"blokir dengan: gatewayctl key block --alias {alias}"
        )
    except GatewayUnavailable as exc:
        if not exc.may_have_applied:
            fail(str(exc), EXIT_UNAVAILABLE)
        fail(
            f"{exc}; key '{alias}' mungkin sudah dibuat di LiteLLM tanpa catatan audit. "
            f"Periksa dengan: gatewayctl key list --user {owner}; bila ada, "
            f"blokir dengan: gatewayctl key block --alias {alias}"
        )
    except ApiError as exc:
        fail(f"LiteLLM menolak permintaan: {exc}")
    typer.echo(raw)


@key_app.command("block")
def key_block(
    ctx: typer.Context,
    user: str | None = typer.Option(None, "--user", help="Blokir semua key aktif user."),
    alias: str | None = typer.Option(None, "--alias", help="Blokir satu key menurut alias."),
) -> None:
    """Pemblokiran darurat tanpa mengubah file."""
    settings: Settings = ctx.obj
    if (user is None) == (alias is None):
        fail("pilih tepat satu: --user atau --alias")
    operator = _require_operator()
    master_key = _master_key()
    client, actual = _connect_and_fetch(settings, master_key)
    audit = _audit(operator)
    try:
        blocked = block_keys(
            actual,
            client,
            audit,
            user_id=normalize_id(user) if user is not None else None,
            alias=alias,
        )
    except BlockError as exc:
        _block_failed(audit, exc)
    if not blocked:
        fail("tidak ada key aktif yang cocok")
    say(f"{len(blocked)} key diblokir.")


@key_app.command("list")
def key_list(
    ctx: typer.Context,
    user: str | None = typer.Option(None, "--user", help="Filter menurut user."),
    team: str | None = typer.Option(None, "--team", help="Filter menurut team."),
) -> None:
    """Daftar key (tanpa key mentah)."""
    settings: Settings = ctx.obj
    master_key = _master_key()
    _, actual = _connect_and_fetch(settings, master_key)
    rows = key_rows(actual, user_id=normalize_id(user) if user is not None else None, team_id=team)
    say("ALIAS\tUSER\tTEAM\tBLOKIR\tSPEND_USD")
    for row in rows:
        say(
            f"{row['key_alias'] or '-'}\t{row['user_id'] or '-'}\t{row['team_id'] or '-'}\t"
            f"{'ya' if row['blocked'] else 'tidak'}\t{row['spend']:.4f}"
        )
