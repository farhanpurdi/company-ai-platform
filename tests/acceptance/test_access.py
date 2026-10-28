"""T01 (model access) and T04 (rate limit) against the mock upstream (spec 8.2)."""

from __future__ import annotations

from helpers import chat, gateway, issue_key

RATE_LIMIT_REQUESTS = 6


def test_t01_finance_cannot_use_reasoning(applied, mock):
    with gateway(issue_key("fin1@local.test")) as client:
        r = chat(client, "company-reasoning")
    assert r.status_code in (401, 403), r.text
    assert "company-reasoning" in r.text
    assert mock.requests() == []


def test_t04_rate_limit_from_gateway(applied, mock):
    # rate1 key: rpm 3. Sequential requests in well under a minute.
    with gateway(issue_key("rate1@local.test")) as client:
        statuses = [chat(client, "company-fast").status_code for _ in range(RATE_LIMIT_REQUESTS)]
    print(f"T04 statuses={statuses}")
    assert 429 in statuses
    assert set(statuses) <= {200, 429}
    assert len(mock.requests()) == statuses.count(200)
