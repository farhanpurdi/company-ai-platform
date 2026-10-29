"""Static checks on the VM profile's TLS choice, HTTP port and access by IP address.

VM_TLS picks the site set in Caddyfile.vm (spec section 10):
  company (default): company certificate from TLS_CERT_DIR.
  internal: Caddy's own CA, so the gateway can run by IP address until there is
  a domain; the admin host then listens on port 8443.
  off: plain HTTP without a certificate.
The allowlist and the VPN restriction are shared by every mode.
"""

import re
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[1]
CADDYFILE_VM = DEPLOY / "caddy" / "Caddyfile.vm"
TLS = {
    "company": "tls /certs/fullchain.pem /certs/privkey.pem",
    "internal": "tls internal",
}


def _vm() -> str:
    return CADDYFILE_VM.read_text(encoding="utf-8")


def _block(pattern: str) -> str:
    match = re.search(pattern, _vm(), re.M | re.S)
    assert match, f"Caddyfile.vm has no block matching {pattern!r}"
    return match.group(1)


def _snippet(name: str) -> str:
    return _block(rf"^\({name}\) \{{\n(.*?)^\}}$")


def _global_options() -> str:
    return _block(r"^\{\n(.*?)^\}$")


def _sites(mode: str) -> list[tuple[str, str]]:
    return re.findall(r"^\t(\S+) \{\n(.*?)^\t\}$", _snippet(f"sites_{mode}"), re.M | re.S)


def _compose_vm() -> dict:
    return yaml.safe_load((DEPLOY / "compose.vm.yaml").read_text(encoding="utf-8"))


def _env_example() -> str:
    return (DEPLOY / "env" / "vm.env.example").read_text(encoding="utf-8")


def test_vm_imports_site_set_selected_by_vm_tls():
    assert re.findall(r"^import sites_.*$", _vm(), re.M) == ["import sites_{$VM_TLS:company}"]


@pytest.mark.parametrize("mode", ["company", "internal"])
def test_https_site_sets(mode):
    assert _sites(mode) == [
        ("{$LLM_HOST}", f"\t\t{TLS[mode]}\n\t\timport inference\n"),
        ("{$LLM_ADMIN_HOST}", f"\t\t{TLS[mode]}\n\t\timport admin\n"),
    ]


def test_off_site_set_is_plain_http_without_certificate():
    assert _sites("off") == [
        ("http://{$LLM_HOST}", "\t\timport inference\n"),
        ("http://{$LLM_ADMIN_HOST}", "\t\timport admin\n"),
    ]


def test_only_https_site_sets_configure_tls():
    assert len(re.findall(r"^\s*tls ", _vm(), re.M)) == 4


def test_route_rules_are_shared_by_every_mode():
    # The allowlist and the VPN restriction are written once, whatever VM_TLS says.
    assert _snippet("inference").split() == ["import", "access_log", "import", "inference_allowlist"]
    admin = _snippet("admin")
    assert re.search(r"^\t@vpn remote_ip \{\$VPN_CIDR\}$", admin, re.M)
    assert re.search(r"^\thandle @vpn \{\n\t\timport litellm_upstream\n\t\}$", admin, re.M)
    assert re.search(r"^\thandle \{\n\t\trespond 403\n\t\}$", admin, re.M)
    text = _vm()
    assert text.count("import inference_allowlist") == 1
    assert text.count("remote_ip") == 1


def test_vm_default_sni_is_inference_host():
    # A client that dials an IP address sends no SNI, and behind Docker's port
    # mapping Caddy cannot fall back to the dialled address: without default_sni
    # the TLS handshake fails.
    assert re.search(r"^\tdefault_sni \{\$LLM_HOST\}$", _global_options(), re.M)


def test_vm_http_port_follows_llm_http_port():
    assert re.search(r"^\thttp_port \{\$LLM_HTTP_PORT:80\}$", _global_options(), re.M)


def test_compose_vm_caddy_env_and_ports():
    caddy = _compose_vm()["services"]["caddy"]
    assert caddy["environment"]["VM_TLS"] == "${VM_TLS:-company}"
    assert caddy["environment"]["LLM_HTTP_PORT"] == "${LLM_HTTP_PORT:-80}"
    # The HTTP port is the same inside and outside the container: in IP mode the
    # tools container reaches the gateway through the published host port.
    assert caddy["ports"] == ["${LLM_HTTP_PORT:-80}:${LLM_HTTP_PORT:-80}", "443:443", "8443:8443"]


def test_compose_vm_gateway_url_can_be_set_for_plain_http():
    tools = _compose_vm()["services"]["tools"]
    assert tools["environment"]["GATEWAY_URL"] == "${GATEWAY_URL:-https://${LLM_HOST}}"


def test_vm_env_example_documents_tls_choice():
    text = _env_example()
    assert re.search(r"^VM_TLS=company$", text, re.M)
    assert "VM_TLS=internal" in text and ":8443" in text
    assert "GATEWAY_CA_BUNDLE=/repo/var/caddy-vm-root.crt" in text
    assert "VM_TLS=off" in text and "GATEWAY_URL=http://10.0.0.5:8080" in text


def test_vm_env_example_documents_http_port():
    assert re.search(r"^LLM_HTTP_PORT=80$", _env_example(), re.M)
