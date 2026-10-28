"""Append-only JSONL audit log (spec 6.6). Raw keys must never reach record()."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path, operator: str, git_sha: str) -> None:
        self.path = Path(path)
        self.operator = operator
        self.git_sha = git_sha

    def ensure_writable(self) -> None:
        """Raise OSError now if the log cannot be appended to, before anything is mutated."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8"):
            pass

    def record(
        self, action: str, target: str, before: Mapping | None, after: Mapping | None
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "operator": self.operator,
            "git_sha": self.git_sha,
            "action": action,
            "target": target,
            "before": before,
            "after": after,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
