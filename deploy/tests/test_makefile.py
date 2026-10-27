"""Static checks on the Makefile targets that run gatewayctl.

`gatewayctl key issue` writes only the raw key to stdout. make echoes each
recipe line to stdout before running it unless the line starts with `@`, so
an unsilenced recipe would make `KEY=$(make ctl ARGS='key issue ...')` capture
the docker compose command line as well as the key.
"""

from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
GATEWAYCTL_TARGETS = ["plan", "apply", "ctl"]


def _recipe(target: str) -> list[str]:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.split(":")[0] == target and ":" in line) + 1
    recipe = []
    for line in lines[start:]:
        if not line.startswith("\t"):
            break
        recipe.append(line[1:])
    return recipe


@pytest.mark.parametrize("target", GATEWAYCTL_TARGETS)
def test_gatewayctl_recipes_are_silent(target):
    recipe = _recipe(target)
    assert recipe, f"target {target} has no recipe"
    for line in recipe:
        assert line.startswith("@"), f"{target}: make would echo {line!r} to stdout"


def test_smoke_target_passes_smoke_key_to_tools():
    recipe = " ".join(_recipe("smoke"))
    assert "-e SMOKE_KEY" in recipe
    assert "pytest" in recipe and "tests/smoke" in recipe


def _prerequisites(target: str) -> list[str]:
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{target}:"):
            return line.split(":", 1)[1].split()
    raise AssertionError(f"no target {target}")


def test_test_target_runs_unit_and_always_scans_t10():
    # Spec section 1: `make test` covers unit, integration and acceptance.
    assert "unit" in _prerequisites("test")
    recipe = _recipe("test")
    assert any("tests/integration tests/acceptance" in line for line in recipe)
    assert "scripts/t10-scan-logs.sh $(ENV)" in recipe
    assert not any("wildcard" in line or "dilewati" in line for line in recipe)


def test_smoke_key_is_not_documented_as_make_argument():
    # A make argument lands in argv, which every user on the host can read via ps.
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "make smoke SMOKE_KEY=" not in text
    checklist = (MAKEFILE.parent / "docs" / "pilot-checklist.md").read_text(encoding="utf-8")
    assert "SMOKE_KEY=\"$SMOKE_KEY\"`" not in checklist
    assert "SMOKE_KEY=\"$SMOKE_KEY\" make smoke ENV=vm" in checklist


def test_audit_git_sha_marks_uncommitted_file():
    text = MAKEFILE.read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("GIT_SHA ="))
    assert "git status --porcelain" in text and "-dirty" in text, line


def test_tools_runs_as_host_user():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "export HOST_UID" in text and "export HOST_GID" in text
    assert "--user $(HOST_UID):$(HOST_GID)" in " ".join(_recipe("unit"))
    compose = (MAKEFILE.parent / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert 'user: "${HOST_UID:-0}:${HOST_GID:-0}"' in compose
