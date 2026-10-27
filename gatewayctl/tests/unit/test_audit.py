import json
from datetime import datetime

from gatewayctl.audit import AuditLog


def test_record_appends_jsonl_line(tmp_path):
    path = tmp_path / "nested" / "dir" / "audit.log"
    log = AuditLog(path, operator="ops@example.com", git_sha="abc123")
    log.record("create_team", "team:dev", None, {"team_id": "dev"})
    log.record("block_key", "key:budi-x", {"token": "t1"}, None)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert set(first) == {"ts", "operator", "git_sha", "action", "target", "before", "after"}
    assert first["operator"] == "ops@example.com"
    assert first["git_sha"] == "abc123"
    assert first["action"] == "create_team"
    assert first["target"] == "team:dev"
    assert first["before"] is None
    assert first["after"] == {"team_id": "dev"}
    assert second["before"] == {"token": "t1"}
    assert second["after"] is None
    assert first["ts"].endswith("+00:00")
    assert datetime.fromisoformat(first["ts"]).utcoffset().total_seconds() == 0


def test_record_appends_to_existing_file(tmp_path):
    path = tmp_path / "audit.log"
    AuditLog(path, "a", "s").record("x", "t", None, None)
    AuditLog(path, "b", "s").record("y", "t", None, None)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
