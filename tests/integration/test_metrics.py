"""/metrics keeps authentication; only the read-only admin scraper key can read it.

Spec Fase 2 5.3 assumed a plain virtual key gets 200. LiteLLM v1.106.4 answers 401
("Only proxy admin ..."), so the owner chose a `proxy_admin_viewer` service account
for the scraper. Plain keys must stay rejected, and the scraper must not reach a model.
"""

from __future__ import annotations

import re

import httpx

from helpers import _env, chat, gateway, issue_key


def _metrics(c: httpx.Client) -> httpx.Response:
    # LiteLLM redirects /metrics to /metrics/ after the auth check; Prometheus follows it too.
    return c.get("/metrics", follow_redirects=True)


def test_metrics_rejects_missing_key(applied):
    r = httpx.get(f"{_env('GATEWAY_URL')}/metrics", timeout=30)
    assert r.status_code == 401


def test_metrics_rejects_plain_virtual_key(applied, mock):
    with gateway(issue_key("dev1@local.test")) as c:
        assert chat(c, "company-fast").status_code == 200
        assert _metrics(c).status_code == 401


def test_scraper_key_reads_metrics(applied, mock):
    with gateway(issue_key("prometheus")) as c:
        r = _metrics(c)
    assert r.status_code == 200
    assert re.search(r"^litellm_\w+", r.text, re.M)


def test_scraper_key_cannot_call_models(applied, mock):
    with gateway(issue_key("prometheus")) as c:
        assert _metrics(c).status_code == 200
        assert chat(c, "company-fast", max_tokens=1).status_code != 200
    assert mock.requests() == []


def test_scraper_key_cannot_write(applied, mock):
    with gateway(issue_key("prometheus")) as c:
        assert c.post("/team/new", json={"team_alias": "scraper-must-not-create"}).status_code == 403


def test_service_metrics_cover_redis_and_postgres(applied, mock):
    with gateway(issue_key("dev1@local.test")) as c:
        assert chat(c, "company-fast").status_code == 200
    with gateway(issue_key("prometheus")) as c:
        text = _metrics(c).text
    assert re.search(r"^litellm_\w*redis\w*", text, re.M | re.I)
    assert re.search(r"^litellm_\w*(postgres|db)\w*", text, re.M | re.I)
