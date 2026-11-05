"""scripts/restore.sh against a stub `docker`, so it runs without a stack.

The stub logs every call to $STUB_DIR/calls. Marker files in $STUB_DIR make a
step fail: list_fail (pg_restore --list) and restore_fail (pg_restore --clean).
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restore.sh"
REDIS_PASSWORD = "fake-redis-pass-123"

STUB_DOCKER = """#!/bin/sh
echo "$*" >>"$STUB_DIR/calls"
case "$*" in
  *" pg_restore --clean"*) cat >/dev/null; [ -f "$STUB_DIR/restore_fail" ] && exit 1; exit 0 ;;
  *" pg_restore --list"*) cat >/dev/null; [ -f "$STUB_DIR/list_fail" ] && exit 1; echo ';toc' ;;
  *" stop "*) exit 0 ;;
  *" up -d --wait "*) exit 0 ;;
  *FLUSHALL*) exit 0 ;;
  *) echo "stub docker: unexpected $*" >&2; exit 9 ;;
esac
"""

DUMP = "var/backups/litellm-20261104T021500Z.dump"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    (tmp_path / "deploy" / "env").mkdir(parents=True)
    (tmp_path / "deploy" / "env" / "local.env").write_text(f"REDIS_PASSWORD={REDIS_PASSWORD}\n")
    (tmp_path / "var" / "backups").mkdir(parents=True)
    (tmp_path / DUMP).write_text("PGDMP-fake")
    stub = tmp_path / "stub"
    (stub / "bin").mkdir(parents=True)
    docker = stub / "bin" / "docker"
    docker.write_text(STUB_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    (stub / "calls").write_text("")
    return tmp_path


def _run(repo: Path, backup: str = DUMP, confirm: bool = True) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PATH": f"{repo / 'stub' / 'bin'}:{os.environ['PATH']}",
        "STUB_DIR": str(repo / "stub"),
    }
    env.pop("CONFIRM", None)
    if confirm:
        env["CONFIRM"] = "1"
    return subprocess.run(
        ["sh", str(repo / "scripts" / SCRIPT.name), "local", backup],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _calls(repo: Path) -> list[str]:
    return (repo / "stub" / "calls").read_text().splitlines()


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_requires_confirm(repo):
    r = _run(repo, confirm=False)
    assert r.returncode == 1
    assert "CONFIRM=1" in r.stderr
    assert "litellm-20261104T021500Z.dump" in r.stderr
    assert _calls(repo) == []


@pytest.mark.parametrize("backup", ["", "var/backups/nope.dump"])
def test_missing_backup_stops_nothing(repo, backup):
    r = _run(repo, backup=backup)
    assert r.returncode == 1
    assert _calls(repo) == []


def test_unreadable_dump_stops_nothing(repo):
    (repo / "stub" / "list_fail").write_text("")
    r = _run(repo)
    assert r.returncode == 1
    calls = _calls(repo)
    assert len(calls) == 1 and "pg_restore --list" in calls[0]


def test_restore_runs_in_order(repo):
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    calls = _calls(repo)
    expected = [
        " pg_restore --list",
        " stop litellm-a litellm-b",
        " pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error -U litellm -d litellm",
        "FLUSHALL",
        " up -d --wait litellm-a litellm-b",
    ]
    pos = -1
    for needle in expected:
        nxt = next((i for i, c in enumerate(calls) if i > pos and needle in c), None)
        assert nxt is not None, f"{needle!r} missing or out of order in {calls}"
        pos = nxt


def test_failed_restore_keeps_replicas_stopped(repo):
    (repo / "stub" / "restore_fail").write_text("")
    r = _run(repo)
    assert r.returncode == 1
    assert not any(" up -d" in c for c in _calls(repo))
    assert "make up" in r.stderr


def test_no_secret_on_command_line(repo):
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert REDIS_PASSWORD not in "\n".join(_calls(repo))
