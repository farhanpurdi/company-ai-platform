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
    start = lines.index(f"{target}:") + 1
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
