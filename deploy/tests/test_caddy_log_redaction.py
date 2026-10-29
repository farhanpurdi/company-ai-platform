"""Static checks that the Caddy access log never records a credential header.

Caddy redacts Authorization, Cookie, Set-Cookie and Proxy-Authorization by
default. LiteLLM also accepts a key from the headers below (SpecialHeaders in
litellm.proxy._types), so each Caddyfile must redact those explicitly. Shared
snippets live in common.caddy, so checks run on each profile with it imported.
"""

import re
import textwrap
from pathlib import Path

import pytest

CADDY_DIR = Path(__file__).resolve().parents[1] / "caddy"
CADDYFILES = sorted(CADDY_DIR.glob("Caddyfile.*"))
COMMON = CADDY_DIR / "common.caddy"
COMMON_IMPORT = "import /etc/caddy/common.caddy"
# Each profile, and for Caddyfile.vm each VM_TLS site set.
PROFILES = [
    ("Caddyfile.local", "company"),
    ("Caddyfile.vm", "company"),
    ("Caddyfile.vm", "internal"),
    ("Caddyfile.vm", "off"),
]
SNIPPET_DEF = re.compile(r"^\(([\w-]+)\) \{\n(.*?)^\}\n", re.M | re.S)
SNIPPET_IMPORT = re.compile(r"^([ \t]*)import ([\w-]+)$", re.M)

# Canonical (Go http.CanonicalHeaderKey) names, as Caddy logs them.
CREDENTIAL_HEADERS = [
    "X-Litellm-Api-Key",
    "Api-Key",
    "X-Api-Key",
    "X-Goog-Api-Key",
    "Ocp-Apim-Subscription-Key",
    "X-Mcp-Auth",
]


def _effective(caddyfile: Path) -> str:
    """The profile as Caddy sees it: the common.caddy import inlined."""
    text = caddyfile.read_text(encoding="utf-8")
    assert text.count(COMMON_IMPORT) == 1, f"{caddyfile.name} must import common.caddy once"
    return text.replace(COMMON_IMPORT, COMMON.read_text(encoding="utf-8"))


def _sites(caddyfile: str, vm_tls: str) -> dict[str, str]:
    """Top-level site blocks as Caddy builds them: every snippet import expanded."""
    text = _effective(CADDY_DIR / caddyfile).replace("{$VM_TLS:company}", vm_tls)
    snippets = {name: textwrap.dedent(body) for name, body in SNIPPET_DEF.findall(text)}
    text = SNIPPET_DEF.sub("", text)
    while match := SNIPPET_IMPORT.search(text):
        indent, name = match.groups()
        body = textwrap.indent(snippets[name], indent).rstrip("\n")
        text = text[: match.start()] + body + text[match.end() :]
    return dict(re.findall(r"^(\S+) \{\n(.*?)^\}$", text, re.M | re.S))


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
    snippet = _snippet(_effective(caddyfile), "access_log")
    assert re.search(r"format filter \{[^}]*wrap json", snippet, re.S)
    rule = rf"^\s*request>headers>{re.escape(header)} (replace REDACTED|delete)\s*$"
    assert re.search(rule, snippet, re.M), f"{header} not redacted in {caddyfile.name}"


@pytest.mark.parametrize(("caddyfile", "vm_tls"), PROFILES)
def test_every_site_uses_access_log_snippet(caddyfile, vm_tls):
    access_log = dict(SNIPPET_DEF.findall(COMMON.read_text(encoding="utf-8")))["access_log"]
    sites = _sites(caddyfile, vm_tls)
    assert len(sites) >= 2
    for address, body in sites.items():
        assert access_log in body, f"{address} has no access_log"
        assert body.count("log {") == 1, f"{address} has a second log block"


@pytest.mark.parametrize("caddyfile", CADDYFILES, ids=lambda p: p.name)
def test_inference_allowlist_matches_raw_path(caddyfile):
    # The `path` matcher cleans `..` segments while reverse_proxy forwards the raw
    # path; the allowlist must compare the raw path exactly (spec 4.2).
    text = _effective(caddyfile)
    assert "@inference path " not in text
    assert (
        '@inference expression `{http.request.uri.path} in ["/v1/chat/completions", '
        '"/v1/models", "/health/liveliness"]`'
    ) in text


@pytest.mark.parametrize(("caddyfile", "vm_tls"), PROFILES)
def test_inference_site_uses_allowlist(caddyfile, vm_tls):
    sites = _sites(caddyfile, vm_tls)
    # Inference address: {$LLM_HOST}, with a scheme or a port in some VM site sets;
    # a site that only redirects to it does not count.
    (inference,) = [b for a, b in sites.items() if "{$LLM_HOST}" in a and "redir " not in b]
    # The only route to LiteLLM is the allowlisted one; everything else is 404.
    assert len(re.findall(r"^\s*reverse_proxy ", inference, re.M)) == 1
    assert re.search(r"^\thandle @inference \{\n\t\treverse_proxy ", inference, re.M)
    assert re.search(r"^\thandle \{\n\t\trespond 404\n\t\}$", inference, re.M)
