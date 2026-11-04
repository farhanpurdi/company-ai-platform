"""scripts/failure-tests.sh against a stub `docker`, so it runs without a stack.

The stub logs every call to $STUB_DIR/calls, prints a fake key for `key issue`
and fails pytest runs while $STUB_DIR/pytest_fail exists.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "failure-tests.sh"
FAKE_KEY = "sk-stubkey0000"
RESTART_ALL = "up -d --wait redis postgres litellm-a litellm-b"

STUB_DOCKER = """#!/bin/sh
echo "$*" >>"$STUB_DIR/calls"
case "$*" in
  *"key issue"*) echo sk-stubkey0000 ;;
  *" pytest "*) [ -f "$STUB_DIR/pytest_fail" ] && exit 1; exit 0 ;;
  *" apply --confirm"*) exit 0 ;;
  *" stop "*) exit 0 ;;
  *" up -d --wait "*) exit 0 ;;
  *) echo "stub docker: unexpected $*" >&2; exit 9 ;;
esac
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    (tmp_path / "deploy" / "env").mkdir(parents=True)
    (tmp_path / "deploy" / "env" / "local.env").write_text("REDIS_PASSWORD=fake\n")
    stub = tmp_path / "stub"
    (stub / "bin").mkdir(parents=True)
    docker = stub / "bin" / "docker"
    docker.write_text(STUB_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    (stub / "calls").write_text("")
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PATH": f"{repo / 'stub' / 'bin'}:{os.environ['PATH']}",
        "STUB_DIR": str(repo / "stub"),
    }
    return subprocess.run(
        ["sh", str(repo / "scripts" / SCRIPT.name), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _calls(repo: Path) -> list[str]:
    return (repo / "stub" / "calls").read_text().splitlines()


def _assert_subsequence(calls: list[str], predicates) -> None:
    pos = -1
    for desc, ok in predicates:
        nxt = next((i for i, c in enumerate(calls) if i > pos and ok(c)), None)
        assert nxt is not None, f"{desc!r} missing or out of order in {calls}"
        pos = nxt


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_refuses_vm(repo):
    r = _run(repo, "vm")
    assert r.returncode == 1
    assert "ENV=local" in r.stderr
    assert _calls(repo) == []


def test_rejects_unknown_scenario(repo):
    r = _run(repo, "local", "t99")
    assert r.returncode == 1
    assert _calls(repo) == []


def test_t12_sequence(repo):
    r = _run(repo, "local", "t12")
    assert r.returncode == 0, r.stderr
    _assert_subsequence(
        _calls(repo),
        [
            ("apply", lambda c: "apply --confirm" in c),
            ("issue 1", lambda c: "key issue" in c),
            ("issue 2", lambda c: "key issue" in c),
            ("prepare", lambda c: "::test_t12_prepare" in c),
            ("stop redis", lambda c: c.endswith(" stop redis")),
            ("redis down", lambda c: "::test_t12_redis_down" in c),
            ("start redis", lambda c: c.endswith(" up -d --wait redis")),
            ("recovered", lambda c: "::test_t12_recovered" in c),
        ],
    )


def test_t13_sequence(repo):
    r = _run(repo, "local", "t13")
    assert r.returncode == 0, r.stderr
    _assert_subsequence(
        _calls(repo),
        [
            ("prepare", lambda c: "::test_t13_prepare" in c),
            ("stop postgres", lambda c: c.endswith(" stop postgres")),
            ("postgres down", lambda c: "::test_t13_postgres_down" in c),
            ("start postgres", lambda c: c.endswith(" up -d --wait postgres")),
            ("recovered", lambda c: "::test_t13_recovered" in c),
        ],
    )


def test_restarts_services_when_a_phase_fails(repo):
    (repo / "stub" / "pytest_fail").write_text("")
    r = _run(repo, "local", "t13")
    assert r.returncode == 1
    assert _calls(repo)[-1].endswith(RESTART_ALL)


def test_restarts_services_after_success_too(repo):
    r = _run(repo, "local", "t12")
    assert r.returncode == 0, r.stderr
    assert _calls(repo)[-1].endswith(RESTART_ALL)


def test_keys_not_in_argv(repo):
    r = _run(repo, "local", "t12", "t13")
    assert r.returncode == 0, r.stderr
    calls = _calls(repo)
    assert not any(FAKE_KEY in c for c in calls)
    assert any("-e T12_RPM_KEY" in c and "-e T12_BUDGET_KEY" in c for c in calls)
    assert any("-e T13_FRESH_KEY" in c and "-e T13_WARM_KEY" in c for c in calls)
