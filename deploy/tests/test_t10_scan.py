"""scripts/t10-scan-logs.sh against a stub `docker`, so it runs without a stack.

The stub answers `compose logs <service>` from logs-<service> files, the psql
row count of the T10 key from spendrows and the psql COPY of LiteLLM_SpendLogs
from spendlogs. Values below are fakes.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "t10-scan-logs.sh"
SERVICES = ["litellm-a", "litellm-b", "postgres", "redis"]

MASTER = "sk-fakemaster0123456789"
OPENAI = "sk-mock-fakeopenai01"
PROMPT = "SENTINEL-PROMPT-1b2c3d4e"
VKEY = "sk-fakevirtualkey9876543"

STUB_DOCKER = """#!/bin/sh
for arg; do last="$arg"; done
case "$*" in
  *psql*" -At "*) cat "$STUB_DIR/spendrows" ;;
  *psql*) cat "$STUB_DIR/spendlogs" ;;
  *" logs "*) cat "$STUB_DIR/logs-$last" 2>/dev/null || true ;;
  *) echo "stub docker: unexpected $*" >&2; exit 9 ;;
esac
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    (tmp_path / "deploy" / "env").mkdir(parents=True)
    (tmp_path / "deploy" / "env" / "local.env").write_text(
        f"LITELLM_MASTER_KEY={MASTER}\nOPENAI_API_KEY={OPENAI}\n"
    )
    (tmp_path / "var").mkdir()
    (tmp_path / "var" / "t10-sentinels.txt").write_text(f"{PROMPT}\n{VKEY}\n")
    stub = tmp_path / "stub"
    (stub / "bin").mkdir(parents=True)
    docker = stub / "bin" / "docker"
    docker.write_text(STUB_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    for svc in SERVICES:
        (stub / f"logs-{svc}").write_text(f'{svc}-1  | {{"level": "INFO", "message": "ok"}}\n')
    (stub / "spendlogs").write_text("req-1\tcompany-fast\t0.01\n")
    (stub / "spendrows").write_text("2\n")
    return tmp_path


def _run(repo: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PATH": f"{repo / 'stub' / 'bin'}:{os.environ['PATH']}",
        "STUB_DIR": str(repo / "stub"),
        "T10_SPEND_WAIT_S": "0",
    }
    return subprocess.run(
        ["sh", str(repo / "scripts" / SCRIPT.name), "local"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_no_values(result: subprocess.CompletedProcess) -> None:
    out = result.stdout + result.stderr
    for value in (MASTER, OPENAI, PROMPT, VKEY):
        assert value not in out


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_clean_logs(repo):
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "T10 clean" in result.stdout


@pytest.mark.parametrize(
    ("source", "value", "name"),
    [
        ("logs-litellm-b", VKEY, "litellm-b"),
        ("logs-postgres", OPENAI, "postgres"),
        ("spendlogs", MASTER, "LiteLLM_SpendLogs"),
    ],
)
def test_leak_names_source_without_value(repo, source, value, name):
    path = repo / "stub" / source
    path.write_text(path.read_text() + f"leaked {value} here\n")
    result = _run(repo)
    assert result.returncode == 1
    assert name in result.stdout + result.stderr
    assert "T10 clean" not in result.stdout
    _assert_no_values(result)


def test_mock_upstream_logs_are_not_scanned(repo):
    (repo / "stub" / "logs-mock-upstream").write_text(f"prompt {PROMPT}\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr


def test_missing_sentinels_file_fails(repo):
    (repo / "var" / "t10-sentinels.txt").unlink()
    result = _run(repo)
    assert result.returncode == 1
    assert "t10-sentinels.txt" in result.stderr


def test_missing_secret_in_env_file_fails(repo):
    (repo / "deploy" / "env" / "local.env").write_text(f"LITELLM_MASTER_KEY={MASTER}\n")
    result = _run(repo)
    assert result.returncode == 1
    assert "OPENAI_API_KEY" in result.stderr
    _assert_no_values(result)


def test_t10_traffic_missing_from_spend_log_fails(repo):
    (repo / "stub" / "spendrows").write_text("1\n")
    result = _run(repo)
    assert result.returncode == 1
    assert "LiteLLM_SpendLogs" in result.stderr
    assert "T10 clean" not in result.stdout
    _assert_no_values(result)


def test_clean_result_names_sources(repo):
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "sumber: litellm-a litellm-b postgres redis postgres:LiteLLM_SpendLogs)" in result.stdout


def test_caddy_logs_are_not_scanned(repo):
    # Caddy is gone (spec 10); a leftover container's log is not a gateway source.
    (repo / "stub" / "logs-caddy").write_text(f"caddy-1  | {PROMPT}\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr
