"""Fixtures shared by tests/integration and tests/acceptance."""

from __future__ import annotations

import pytest

from helpers import Mock, run_ctl


@pytest.fixture(scope="session")
def applied() -> None:
    """Bring LiteLLM in line with entitlements/local.yaml once per session."""
    result = run_ctl("apply", "--confirm")
    assert result.returncode == 0, f"apply local.yaml gagal (exit {result.returncode}): {result.stderr}"


@pytest.fixture
def mock():
    m = Mock()
    m.reset()
    try:
        yield m
    finally:
        m.close()
