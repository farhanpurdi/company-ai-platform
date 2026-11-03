"""Spend follows the prices pinned in deploy/litellm/config.yaml, cache reads and writes included.

T11 compares gateway spend with OpenAI's bill. OpenCode resends the whole
conversation on every step, so most of its input is billed at the cache read price,
and the new part of it at the cache write price.
"""

from __future__ import annotations

import pytest

from helpers import chat, gateway, issue_key, model_prices, settled_key_spend

ALIAS = "company-fast"
PROMPT_TOKENS = 1000
CACHED_TOKENS = 800
CACHE_WRITE_TOKENS = 150
COMPLETION_TOKENS = 500


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_spend_bills_cache_reads_and_writes_at_pinned_prices(applied, mock, stream):
    prices = model_prices(ALIAS)
    expected = (
        (PROMPT_TOKENS - CACHED_TOKENS - CACHE_WRITE_TOKENS) * prices["input_cost_per_token"]
        + CACHED_TOKENS * prices["cache_read_input_token_cost"]
        + CACHE_WRITE_TOKENS * prices["cache_creation_input_token_cost"]
        + COMPLETION_TOKENS * prices["output_cost_per_token"]
    )
    mock.usage(PROMPT_TOKENS, COMPLETION_TOKENS, cached_tokens=CACHED_TOKENS, cache_write_tokens=CACHE_WRITE_TOKENS)
    key = issue_key("fin1@local.test")
    with gateway(key) as client:
        r = chat(client, ALIAS, stream=stream)
    assert r.status_code == 200, r.text[:300]
    # Half the expected spend only proves the spend writer flushed; a gateway
    # billing too little or too much then fails the comparison below.
    assert settled_key_spend(key, expected / 2) == pytest.approx(expected, rel=1e-6)
