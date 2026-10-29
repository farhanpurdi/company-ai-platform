"""Static checks on the LiteLLM settings the spec locks (spec 5)."""

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "litellm" / "config.yaml"


def test_budget_enforcement_fails_closed():
    # Without it LiteLLM admits requests near the limit on a shrunken reservation,
    # and parallel requests overshoot the budget (T03).
    settings = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["general_settings"]
    assert settings.get("fail_closed_budget_enforcement") is True
