"""Static checks that the Caddy access log never records a credential header.

Caddy redacts Authorization, Cookie, Set-Cookie and Proxy-Authorization by
default. LiteLLM also accepts a key from the headers below (SpecialHeaders in
litellm.proxy._types), so each Caddyfile must redact those explicitly.
"""

import re
from pathlib import Path

import pytest

CADDY_DIR = Path(__file__).resolve().parents[1] / "caddy"
CADDYFILES = sorted(CADDY_DIR.glob("Caddyfile.*"))

# Canonical (Go http.CanonicalHeaderKey) names, as Caddy logs them.
CREDENTIAL_HEADERS = [
    "X-Litellm-Api-Key",
    "Api-Key",
    "X-Api-Key",
    "X-Goog-Api-Key",
    "Ocp-Apim-Subscription-Key",
    "X-Mcp-Auth",
]


def _snippet(text: str, name: str) -> str:
    start = text.index(f"({name}) {{")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"unterminated snippet {name}")


def test_both_profiles_present():
    assert {p.name for p in CADDYFILES} == {"Caddyfile.local", "Caddyfile.vm"}


@pytest.mark.parametrize("caddyfile", CADDYFILES, ids=lambda p: p.name)
@pytest.mark.parametrize("header", CREDENTIAL_HEADERS)
def test_access_log_redacts_credential_header(caddyfile, header):
    snippet = _snippet(caddyfile.read_text(), "access_log")
    assert re.search(r"format filter \{[^}]*wrap json", snippet, re.S)
    rule = rf"^\s*request>headers>{re.escape(header)} (replace REDACTED|delete)\s*$"
    assert re.search(rule, snippet, re.M), f"{header} not redacted in {caddyfile.name}"


@pytest.mark.parametrize("caddyfile", CADDYFILES, ids=lambda p: p.name)
def test_every_site_uses_access_log_snippet(caddyfile):
    text = caddyfile.read_text()
    assert "\n\tlog {" not in text.replace(_snippet(text, "access_log"), "")
    sites = re.findall(r"^\{\$LLM(?:_ADMIN)?_HOST\} \{", text, re.M)
    assert len(sites) == 2
    assert text.count("import access_log") == len(sites)


@pytest.mark.parametrize("caddyfile", CADDYFILES, ids=lambda p: p.name)
def test_inference_allowlist_matches_raw_path(caddyfile):
    # The `path` matcher cleans `..` segments while reverse_proxy forwards the raw
    # path; the allowlist must compare the raw path exactly (spec 4.2).
    text = caddyfile.read_text(encoding="utf-8")
    assert "@inference path " not in text
    assert (
        '@inference expression `{http.request.uri.path} in ["/v1/chat/completions", '
        '"/v1/models", "/health/liveliness"]`'
    ) in text
