"""scripts/backup.sh against a stub `docker`, so it runs without a stack.

The stub logs every call to $STUB_DIR/calls. Marker files in $STUB_DIR make a
step fail: dump_fail (pg_dump) and list_fail (pg_restore --list).
"""

import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup.sh"

STUB_DOCKER = """#!/bin/sh
echo "$*" >>"$STUB_DIR/calls"
case "$*" in
  *" pg_dump "*) [ -f "$STUB_DIR/dump_fail" ] && exit 1; printf 'PGDMP-fake' ;;
  *" pg_restore --list"*) cat >/dev/null; [ -f "$STUB_DIR/list_fail" ] && exit 1; echo ';toc' ;;
  *) echo "stub docker: unexpected $*" >&2; exit 9 ;;
esac
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    (tmp_path / "deploy" / "env").mkdir(parents=True)
    (tmp_path / "deploy" / "env" / "local.env").write_text("REDIS_PASSWORD=fake-redis-pass-123\n")
    stub = tmp_path / "stub"
    (stub / "bin").mkdir(parents=True)
    docker = stub / "bin" / "docker"
    docker.write_text(STUB_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    (stub / "calls").write_text("")
    return tmp_path


def _run(repo: Path, **extra_env) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PATH": f"{repo / 'stub' / 'bin'}:{os.environ['PATH']}",
        "STUB_DIR": str(repo / "stub"),
        **extra_env,
    }
    return subprocess.run(
        ["sh", str(repo / "scripts" / SCRIPT.name), "local"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _calls(repo: Path) -> str:
    return (repo / "stub" / "calls").read_text()


def _age(path: Path, days: int) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def _leftovers(repo: Path) -> list[str]:
    d = repo / "var" / "backups"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_backup_writes_private_dump(repo):
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    path = r.stdout.strip()
    assert re.fullmatch(r"var/backups/litellm-\d{8}T\d{6}Z\.dump", path)
    dump = repo / path
    assert dump.read_text() == "PGDMP-fake"
    assert stat.S_IMODE(dump.stat().st_mode) == 0o600
    assert stat.S_IMODE((repo / "var" / "backups").stat().st_mode) == 0o700
    assert not [n for n in _leftovers(repo) if n.endswith(".partial")]
    assert "backup ok:" in r.stderr


@pytest.mark.parametrize("marker", ["list_fail", "dump_fail"])
def test_failed_backup_leaves_no_file(repo, marker):
    (repo / "stub" / marker).write_text("")
    r = _run(repo)
    assert r.returncode == 1
    assert r.stdout == ""
    assert "backup gagal" in r.stderr
    assert _leftovers(repo) == []


def _seed_retention(repo: Path) -> Path:
    d = repo / "var" / "backups"
    d.mkdir(parents=True)
    for name, days in (("litellm-old.dump", 8), ("litellm-recent.dump", 6), ("backup.log", 30)):
        (d / name).write_text("x")
        _age(d / name, days)
    return d


def test_retention_deletes_only_old_dumps(repo):
    d = _seed_retention(repo)
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert not (d / "litellm-old.dump").exists()
    assert (d / "litellm-recent.dump").exists()
    assert (d / "backup.log").exists()


def test_retention_skipped_when_backup_fails(repo):
    d = _seed_retention(repo)
    (repo / "stub" / "dump_fail").write_text("")
    r = _run(repo)
    assert r.returncode == 1
    for name in ("litellm-old.dump", "litellm-recent.dump", "backup.log"):
        assert (d / name).exists()


@pytest.mark.parametrize("value", ["0", "abc", "-1"])
def test_rejects_bad_keep_days(repo, value):
    r = _run(repo, BACKUP_KEEP_DAYS=value)
    assert r.returncode == 1
    assert _calls(repo) == ""


def test_refuses_to_overwrite_existing_dump(repo):
    fake_bin = repo / "stub" / "bin"
    date = fake_bin / "date"
    date.write_text("#!/bin/sh\necho 20261104T021500Z\n")
    date.chmod(date.stat().st_mode | stat.S_IXUSR)
    d = repo / "var" / "backups"
    d.mkdir(parents=True)
    existing = d / "litellm-20261104T021500Z.dump"
    existing.write_text("old")
    r = _run(repo)
    assert r.returncode == 1
    assert existing.read_text() == "old"


def test_stdout_is_only_the_path(repo):
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == 1
