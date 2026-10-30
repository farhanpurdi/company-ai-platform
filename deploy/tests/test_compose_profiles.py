"""Static checks on the compose profiles: no reverse proxy, only litellm-a is published,
no price data fetched at startup (spec 4.1, 4.2, 5, 10)."""

import re
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[1]
REPO = DEPLOY.parent
COMPOSE_FILES = ["compose.yaml", "compose.local.yaml", "compose.vm.yaml"]
# Variables that only Caddy and TLS used; old env files may still carry them.
REMOVED_VARS = ["VM_TLS", "LLM_HOST", "LLM_ADMIN_HOST", "LLM_HTTP_PORT", "LLM_HTTPS_PORT",
                "TLS_CERT_DIR", "VPN_CIDR", "GATEWAY_CA_BUNDLE"]


def _compose(name: str) -> dict:
    return yaml.safe_load((DEPLOY / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_no_caddy_service(name):
    assert "caddy" not in _compose(name)["services"]


def test_caddy_config_and_volumes_are_gone():
    assert not (DEPLOY / "caddy").exists()
    assert set(_compose("compose.yaml")["volumes"]) == {"pgdata"}


def test_base_compose_publishes_nothing():
    assert [s for s, d in _compose("compose.yaml")["services"].items() if "ports" in d] == []


@pytest.mark.parametrize(
    ("name", "ports"),
    [
        ("compose.local.yaml", ["127.0.0.1:${LITELLM_PORT:-4000}:4000"]),
        ("compose.vm.yaml", ["${LITELLM_PORT:-4000}:4000"]),
    ],
)
def test_only_litellm_a_is_published(name, ports):
    services = _compose(name)["services"]
    assert [s for s, d in services.items() if "ports" in d] == ["litellm-a"]
    assert services["litellm-a"]["ports"] == ports


def test_tools_reaches_litellm_a_inside_compose_network():
    env = _compose("compose.yaml")["services"]["tools"]["environment"]
    assert env["LITELLM_BASE_URL"] == "http://litellm-a:4000"
    assert env["GATEWAY_URL"] == "http://litellm-a:4000"
    for name in ("compose.local.yaml", "compose.vm.yaml"):
        overlay = _compose(name)["services"]["tools"].get("environment", {})
        assert "GATEWAY_URL" not in overlay and "GATEWAY_CA_BUNDLE" not in overlay


@pytest.mark.parametrize(
    "path",
    ["deploy/compose.yaml", "deploy/compose.local.yaml", "deploy/compose.vm.yaml",
     "deploy/env/vm.env.example", "deploy/env/local.env.example", "scripts/init-local.sh"],
)
def test_removed_variables_are_gone(path):
    text = (REPO / path).read_text(encoding="utf-8")
    assert [v for v in REMOVED_VARS if re.search(rf"\b{v}\b", text)] == []


def test_vm_env_example_sets_litellm_port():
    text = (DEPLOY / "env" / "vm.env.example").read_text(encoding="utf-8")
    assert re.search(r"^LITELLM_PORT=4000$", text, re.M)


@pytest.mark.parametrize("service", ["litellm-a", "litellm-b"])
def test_litellm_uses_cost_map_from_image(service):
    # Otherwise LiteLLM downloads its cost map from GitHub main at every start, and
    # unreviewed cached-input prices and output limits change budgets (spec 5).
    env = _compose("compose.yaml")["services"][service]["environment"]
    assert env.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True"
