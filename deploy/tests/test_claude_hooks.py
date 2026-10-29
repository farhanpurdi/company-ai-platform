"""Claude Code PreToolUse hooks that block CLAUDE.md violations before a tool runs.

The scripts read the hook's JSON from stdin and match it as raw text (no jq or
Python on the host). Deny: exit 2 with the reason on stderr. Ask: exit 0 with a
permissionDecision JSON on stdout. Allow: exit 0, no output.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"

DENY_BASH = [
    "docker compose -p llm-gateway-local -f deploy/compose.yaml down -v",
    "docker compose -p llm-gateway-vm down --volumes",
    "docker volume rm llm-gateway-local_pgdata",
    "docker volume prune -f",
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "cat deploy/env/local.env",
    "grep MASTER deploy/env/vm.env",
    "head -3 deploy/env/local.env",
    "LITELLM_LOG=DEBUG make up",
    "make down; LITELLM_LOG=DEBUG make up",
    "export LITELLM_LOG=DEBUG",
    "docker run -e LITELLM_LOG=DEBUG ghcr.io/berriai/litellm",
]
ALLOW_BASH = [
    "docker compose -p llm-gateway-vmverify -f deploy/compose.yaml down -v",
    "make down",
    "git commit -m 'feat: x'",
    "cat deploy/env/vm.env.example",
    "make unit",
    "docker compose --env-file deploy/env/local.env run --rm -T tools pytest -q | grep passed",
    # Naming the setting in a commit message does not set it.
    "git commit -m 'deny LITELLM_LOG=DEBUG and fail-open settings'",
]


def _denied(r: subprocess.CompletedProcess) -> bool:
    # sh itself exits 2 when the script is missing; a real deny names the hook.
    return r.returncode == 2 and r.stderr.startswith("hook: ")


def _run(script: str, tool_input: dict, tool_name: str = "Bash") -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input}
    return subprocess.run(
        ["sh", str(HOOKS / script)], input=json.dumps(payload), capture_output=True, text=True, timeout=30
    )


@pytest.mark.parametrize("cmd", DENY_BASH)
def test_bash_guard_denies(cmd):
    assert _denied(_run("guard-bash.sh", {"command": cmd}))


@pytest.mark.parametrize("cmd", ALLOW_BASH)
def test_bash_guard_allows(cmd):
    r = _run("guard-bash.sh", {"command": cmd})
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_git_push_asks_owner():
    r = _run("guard-bash.sh", {"command": "git push -u origin feat/remove-caddy"})
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "ask" and out["permissionDecisionReason"]


@pytest.mark.parametrize(
    ("tool_input", "code"),
    [
        ({"file_path": "/x/deploy/env/local.env"}, 2),
        ({"file_path": "/x/deploy/env/vm.env.example"}, 0),
        ({"file_path": "/x/deploy/compose.yaml", "old_string": "INFO", "new_string": "  LITELLM_LOG: DEBUG"}, 2),
        ({"file_path": "/x/deploy/litellm/config.yaml", "content": "allow_requests_on_db_unavailable: true"}, 2),
        ({"file_path": "/x/deploy/litellm/config.yaml", "new_string": "  cache: true"}, 2),
        ({"file_path": "/x/docs/operator-guide.md", "new_string": "Jangan set LITELLM_LOG: DEBUG"}, 0),
        ({"file_path": "/x/deploy/compose.yaml", "new_string": "  LITELLM_LOG: INFO"}, 0),
    ],
)
def test_file_guard(tool_input, code):
    r = _run("guard-files.sh", tool_input, tool_name="Edit")
    if code == 2:
        assert _denied(r), r.stderr
    else:
        assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_settings_wire_both_guards():
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pre = {m["matcher"]: m["hooks"][0]["command"] for m in settings["hooks"]["PreToolUse"]}
    assert pre == {
        "Bash": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard-bash.sh',
        "Read|Edit|Write": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard-files.sh',
    }
    assert "Stop" not in settings["hooks"]  # the success gate is personal (plan Task 0b)


@pytest.mark.parametrize("script", ["guard-bash.sh", "guard-files.sh"])
def test_scripts_are_executable(script):
    assert (HOOKS / script).stat().st_mode & 0o111
