"""Unit tests for the pure parts of tests/smoke/spend_report.py (T11)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tests" / "smoke" / "spend_report.py"


@pytest.fixture(scope="module")
def spend_report():
    spec = importlib.util.spec_from_file_location("spend_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_reads_team_spend(spend_report):
    infos = {
        "it-developer": {"team_info": {"team_id": "it-developer", "spend": 1.5}},
        "finance": {"team_info": {"team_id": "finance", "spend": None}},
    }
    snap = spend_report.snapshot(infos, ts="2026-10-27T10:00:00+00:00")
    assert snap == {
        "ts": "2026-10-27T10:00:00+00:00",
        "teams": {"it-developer": 1.5, "finance": 0.0},
    }


def test_compare_prints_delta_per_team(spend_report):
    before = {"ts": "a", "teams": {"it-developer": 1.0, "finance": 0.5}}
    after = {"ts": "b", "teams": {"it-developer": 1.25, "finance": 0.5, "hr": 0.1}}
    delta = spend_report.compare(before, after)
    assert delta["from"] == "a" and delta["to"] == "b"
    assert delta["teams"] == {"it-developer": pytest.approx(0.25), "finance": 0.0, "hr": pytest.approx(0.1)}
    assert delta["total"] == pytest.approx(0.35)
