"""The Prometheus scraper service account is identical in both profiles (spec Fase 2 5.2, 5.3)."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["pilot.yaml", "local.yaml"])
def test_prometheus_service_account(name):
    doc = yaml.safe_load((ROOT / "entitlements" / name).read_text(encoding="utf-8"))
    assert doc["service_accounts"]["prometheus"] == {
        "team": "it-developer",
        "models": ["company-fast"],
        "rpm_limit": 10,
        "budgets": [{"duration": "30d", "max_usd": 0}],
        # Plain virtual keys get 401 on /metrics (LiteLLM v1.106.4): only a proxy admin or
        # the read-only admin viewer may scrape. Owner decision on spec Fase 2 5.3.
        "role": "proxy_admin_viewer",
    }
