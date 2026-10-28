"""Inference host allowlist (spec 4.2): only the listed paths reach LiteLLM.

Paths are sent byte for byte with http.client: httpx would resolve dot
segments before sending, which is exactly the case under test. Caddy answers
a blocked path with an empty 404; LiteLLM's own 404 has a JSON body.
"""

from __future__ import annotations

import http.client
import os
import ssl
from urllib.parse import urlsplit

import pytest

BLOCKED = [
    "/key/list",
    "/key/list/../../v1/models",
    "/openai/x/../../v1/models",
    "/files/x/../../v1/models",
    "/batches/x/../../v1/models",
    "/credentials/x/../../v1/models",
    "/openai/x/%2e%2e/%2e%2e/v1/models",
    "/files/x/..%2f..%2fv1/models",
    "/v1/./models",
    "/V1/MODELS",
]


def _get(path: str) -> tuple[int, bytes]:
    url = urlsplit(os.environ["GATEWAY_URL"])
    bundle = os.environ.get("GATEWAY_CA_BUNDLE")
    context = ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()
    conn = http.client.HTTPSConnection(url.hostname, url.port or 443, context=context, timeout=30)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


@pytest.mark.parametrize("path", BLOCKED)
def test_non_allowlisted_path_is_404_from_caddy(mock, path):
    status, body = _get(path)
    assert (status, body) == (404, b""), f"{path} -> {status} {body[:80]!r}"
    assert mock.requests() == []


def test_allowlisted_path_reaches_litellm(mock):
    status, body = _get("/v1/models")
    # No key: LiteLLM itself answers, so the path was forwarded.
    assert status == 401, body[:200]
