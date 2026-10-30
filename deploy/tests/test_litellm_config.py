"""Static checks on the LiteLLM settings the spec locks (spec 5)."""

from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[1] / "litellm" / "config.yaml"
PRICE_KEYS = ("input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost")


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_budget_enforcement_fails_closed():
    # Without it LiteLLM admits requests near the limit on a shrunken reservation,
    # and parallel requests overshoot the budget (T03).
    settings = _config()["general_settings"]
    assert settings.get("fail_closed_budget_enforcement") is True


@pytest.mark.parametrize("entry", _config()["model_list"], ids=lambda e: e["model_name"])
def test_alias_pins_every_price(entry):
    # A price left out comes from LiteLLM's cost map instead of a reviewed value
    # (spec 5). YAML 1.1 reads 2e-7 (no dot) as a string, so the type is checked too.
    info = entry["model_info"]
    assert {k: type(info.get(k)).__name__ for k in PRICE_KEYS} == {k: "float" for k in PRICE_KEYS}
