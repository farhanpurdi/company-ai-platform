"""Gateway spend per team, for the T11 reconciliation against OpenAI usage.

  python tests/smoke/spend_report.py > before.json     # before the smoke run
  python tests/smoke/spend_report.py --compare before.json   # after: spend delta

Needs LITELLM_BASE_URL and LITELLM_MASTER_KEY (set inside the `tools` container).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def snapshot(team_infos: dict[str, dict], *, ts: str | None = None) -> dict:
    """{"ts", "teams": {team_id: spend}} from `team_info` responses keyed by team id."""
    return {
        "ts": ts or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": {tid: float((info.get("team_info") or {}).get("spend") or 0.0) for tid, info in team_infos.items()},
    }


def compare(before: dict, after: dict) -> dict:
    teams = {tid: spend - before["teams"].get(tid, 0.0) for tid, spend in after["teams"].items()}
    return {"from": before["ts"], "to": after["ts"], "teams": teams, "total": sum(teams.values())}


def _collect() -> dict:
    # Imported here so the pure functions above load without the stack environment.
    from helpers import admin

    with admin() as client:
        ids = [t["team_id"] for t in client.list_teams()]
        return snapshot({tid: client.team_info(tid) for tid in ids})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--compare", metavar="BEFORE.json", help="cetak selisih spend terhadap snapshot sebelumnya")
    args = parser.parse_args(argv)
    now = _collect()
    result = compare(json.loads(Path(args.compare).read_text()), now) if args.compare else now
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
