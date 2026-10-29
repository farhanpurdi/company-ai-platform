"""Static checks on the VM profile's TLS choice and access by IP address.

VM_TLS=company (default) serves the company certificate from TLS_CERT_DIR.
VM_TLS=internal uses Caddy's own CA so the gateway can run by IP address until
there is a domain (spec section 10); the admin host then listens on port 8443.
"""

import re
from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[1]
CADDYFILE_VM = DEPLOY / "caddy" / "Caddyfile.vm"
TLS_IMPORT = "import tls_{$VM_TLS:company}"


def _vm() -> str:
    return CADDYFILE_VM.read_text(encoding="utf-8")


def test_vm_tls_snippets():
    text = _vm()
    assert re.search(r"^\(tls_company\) \{\n\ttls /certs/fullchain\.pem /certs/privkey\.pem\n\}$", text, re.M)
    assert re.search(r"^\(tls_internal\) \{\n\ttls internal\n\}$", text, re.M)


def test_every_vm_site_imports_selected_tls():
    text = _vm()
    sites = re.findall(r"^\{\$LLM(?:_ADMIN)?_HOST\} \{", text, re.M)
    assert len(sites) == 2
    assert text.count(TLS_IMPORT) == len(sites)
    # The only tls directives are the two snippets.
    assert len(re.findall(r"^\s*tls ", text, re.M)) == 2


def test_vm_default_sni_is_inference_host():
    # A client that dials an IP address sends no SNI, and behind Docker's port
    # mapping Caddy cannot fall back to the dialled address: without default_sni
    # the TLS handshake fails.
    global_options = re.search(r"^\{\n(.*?)^\}$", _vm(), re.M | re.S)
    assert global_options, "Caddyfile.vm has no global options block"
    assert re.search(r"^\tdefault_sni \{\$LLM_HOST\}$", global_options.group(1), re.M)


def test_compose_vm_passes_vm_tls_and_publishes_admin_port():
    doc = yaml.safe_load((DEPLOY / "compose.vm.yaml").read_text(encoding="utf-8"))
    caddy = doc["services"]["caddy"]
    assert caddy["environment"]["VM_TLS"] == "${VM_TLS:-company}"
    assert "8443:8443" in caddy["ports"]


def test_vm_env_example_documents_tls_choice():
    text = (DEPLOY / "env" / "vm.env.example").read_text(encoding="utf-8")
    assert re.search(r"^VM_TLS=company$", text, re.M)
    assert "VM_TLS=internal" in text and ":8443" in text
    assert "GATEWAY_CA_BUNDLE=/repo/var/caddy-vm-root.crt" in text
