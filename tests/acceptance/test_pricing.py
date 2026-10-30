"""Spend follows the prices pinned in deploy/litellm/config.yaml, cached input included.

T11 compares gateway spend with OpenAI's bill. OpenCode resends the whole
conversation on every step, so most of its input is billed at the cache price.
"""

from __future__ import annotations

import pytest

from helpers import chat, gateway, issue_key, model_prices, settled_key_spend

ALIAS = "company-fast"
PROMPT_TOKENS = 1000
CACHED_TOKENS = 800
COMPLETION_TOKENS = 500


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_spend_bills_cached_input_at_pinned_cache_price(applied, mock, stream):
    prices = model_prices(ALIAS)
    expected = (
        (PROMPT_TOKENS - CACHED_TOKENS) * prices["input_cost_per_token"]
        + CACHED_TOKENS * prices["cache_read_input_token_cost"]
        + COMPLETION_TOKENS * prices["output_cost_per_token"]
    )
    mock.usage(PROMPT_TOKENS, COMPLETION_TOKENS, cached_tokens=CACHED_TOKENS)
    key = issue_key("fin1@local.test")
    with gateway(key) as client:
        r = chat(client, ALIAS, stream=stream)
    assert r.status_code == 200, r.text[:300]
    # Half the expected spend only proves the spend writer flushed; a gateway
    # billing too little or too much then fails the comparison below.
    assert settled_key_spend(key, expected / 2) == pytest.approx(expected, rel=1e-6)
