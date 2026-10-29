"""Operator and user docs describe the gateway without Caddy or TLS (spec 4.2, 10)."""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# Instructions that no longer work. Case-insensitive.
STALE = [
    "make local-ca", "make vm-ca", "-f caddy", "caddy-local-root", "caddy-vm-root", "VM_TLS", "LLM_HOST", "LLM_ADMIN_HOST", "LLM_HTTP_PORT",
    "LLM_HTTPS_PORT", "VPN_CIDR", "TLS_CERT_DIR", "GATEWAY_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    "llm.pilot.test", "--resolve", "--cacert", "https://llm", "https://10.", "https://<ip",
]
# Path -> text that must appear.
DOCS = {
    "docs/setup-admin.md": ["LITELLM_PORT", "http://127.0.0.1:4000", "http://10.0.0.5:4000/v1"],
}


@pytest.mark.parametrize("path", sorted(DOCS))
def test_no_stale_instructions(path):
    text = (REPO / path).read_text(encoding="utf-8").lower()
    assert [s for s in STALE if s.lower() in text] == []


@pytest.mark.parametrize("path", sorted(DOCS))
def test_required_facts(path):
    text = (REPO / path).read_text(encoding="utf-8")
    assert [s for s in DOCS[path] if s not in text] == []
