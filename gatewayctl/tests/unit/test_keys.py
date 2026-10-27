import json

import pytest

from fakes import RAW_KEY, RecordingClient
from gatewayctl.audit import AuditLog
from gatewayctl.keys import block_keys, issue_key, key_rows
from gatewayctl.model import (
    ActualKey,
    ActualState,
    BudgetWindow,
    DesiredState,
    KeyPolicy,
    MemberSpec,
    TeamSpec,
)

MODELS = frozenset({"company-fast", "company-coding"})
POLICY = KeyPolicy(MODELS, 60, (BudgetWindow("24h", 10), BudgetWindow("30d", 100)))
TEAM = TeamSpec("dev", "Dev", MODELS, 500.0, "30d", 600)


def desired():
    return DesiredState(
        teams={"dev": TEAM},
        members={
            "budi@perusahaan.com": MemberSpec("budi@perusahaan.com", "dev", 100.0),
            "svc-bot": MemberSpec("svc-bot", "dev", None, "service_account"),
        },
        key_policies={
            "budi@perusahaan.com": POLICY,
            "svc-bot": KeyPolicy(frozenset({"company-fast"}), 120, (BudgetWindow("30d", 50),)),
        },
    )


def akey(alias, user, token, *, team="dev", blocked=False, managed=True, spend=0.0):
    return ActualKey(token, alias, user, team, blocked, POLICY, managed, spend)


def state(*keys):
    return ActualState({"dev": TEAM}, frozenset({"dev"}), (), tuple(keys))


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.log", "ops@example.com", "sha1")


def test_issue_key_uses_policy_and_alias(audit):
    client = RecordingClient()
    raw = issue_key(desired(), state(), client, audit, "budi@perusahaan.com", "opencode")
    assert raw == RAW_KEY
    assert client.calls == [
        (
            "key_generate",
            {
                "user_id": "budi@perusahaan.com",
                "team_id": "dev",
                "key_alias": "budi@perusahaan.com-opencode",
                "models": ["company-coding", "company-fast"],
                "rpm_limit": 60,
                "budget_limits": [
                    {"budget_duration": "24h", "max_budget": 10},
                    {"budget_duration": "30d", "max_budget": 100},
                ],
                "metadata": {"managed_by": "gatewayctl", "owner_kind": "user"},
            },
        )
    ]


def test_issue_key_for_service_account_sets_owner_kind(audit):
    client = RecordingClient()
    issue_key(desired(), state(), client, audit, "svc-bot", "prod")
    payload = client.calls[0][1]
    assert payload["key_alias"] == "svc-bot-prod"
    assert payload["metadata"]["owner_kind"] == "service_account"
    assert payload["models"] == ["company-fast"]


def test_issue_key_unknown_owner_rejected(audit):
    client = RecordingClient()
    with pytest.raises(ValueError, match="nobody@x.com"):
        issue_key(desired(), state(), client, audit, "nobody@x.com", "opencode")
    assert client.calls == []


def test_issue_key_existing_alias_rejected(audit):
    # Review Focus 5: no second key may be issued for a used label (blocked keys count too).
    for existing in (
        akey("budi@perusahaan.com-opencode", "budi@perusahaan.com", "t1"),
        akey("budi@perusahaan.com-opencode", "budi@perusahaan.com", "t1", blocked=True),
    ):
        client = RecordingClient()
        with pytest.raises(ValueError, match="budi@perusahaan.com-opencode"):
            issue_key(desired(), state(existing), client, audit, "budi@perusahaan.com", "opencode")
        assert client.calls == []
    assert not audit.path.exists()


def test_audit_never_contains_raw_key(audit):
    issue_key(desired(), state(), RecordingClient(), audit, "budi@perusahaan.com", "opencode")
    text = audit.path.read_text(encoding="utf-8")
    assert RAW_KEY not in text
    entry = json.loads(text.splitlines()[0])
    assert entry["action"] == "issue_key"
    assert entry["target"] == "key:budi@perusahaan.com-opencode"
    assert entry["after"]["token"] == "hash-new-0001"


@pytest.mark.parametrize("echo_field", ["token", "token_id"])
def test_audit_hashes_token_when_api_echoes_raw_key(audit, echo_field):
    client = RecordingClient()
    client.key_generate = lambda payload: {"key": RAW_KEY, echo_field: RAW_KEY}
    issue_key(desired(), state(), client, audit, "budi@perusahaan.com", "opencode")
    text = audit.path.read_text(encoding="utf-8")
    assert RAW_KEY not in text
    token = json.loads(text.splitlines()[0])["after"]["token"]
    assert len(token) == 64 and not token.startswith("sk-")


def test_audit_prefers_token_id(audit):
    client = RecordingClient()
    client.key_generate = lambda payload: {"key": RAW_KEY, "token": "tok-x", "token_id": "hash-id"}
    issue_key(desired(), state(), client, audit, "budi@perusahaan.com", "opencode")
    assert json.loads(audit.path.read_text(encoding="utf-8"))["after"]["token"] == "hash-id"


def test_block_by_user_blocks_all_active_keys(audit):
    keys = (
        akey("budi-a", "budi@perusahaan.com", "tok-a"),
        akey("budi-b", "budi@perusahaan.com", "tok-b", managed=False),
        akey("budi-old", "budi@perusahaan.com", "tok-old", blocked=True),
        akey("other", "sari@perusahaan.com", "tok-other"),
    )
    client = RecordingClient()
    tokens = block_keys(state(*keys), client, audit, user_id="budi@perusahaan.com")
    assert tokens == ["tok-a", "tok-b"]
    assert client.calls == [("key_block", "tok-a"), ("key_block", "tok-b")]
    lines = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert [(e["action"], e["target"]) for e in lines] == [
        ("block_key", "key:budi-a"),
        ("block_key", "key:budi-b"),
    ]
    assert lines[0]["before"]["token"] == "tok-a"


def test_block_by_alias_blocks_only_that_key(audit):
    keys = (akey("budi-a", "budi@perusahaan.com", "tok-a"), akey("budi-b", "budi@perusahaan.com", "tok-b"))
    client = RecordingClient()
    assert block_keys(state(*keys), client, audit, alias="budi-b") == ["tok-b"]
    assert client.calls == [("key_block", "tok-b")]


def test_block_without_selector_rejected(audit):
    with pytest.raises(ValueError):
        block_keys(state(), RecordingClient(), audit)


def test_key_rows_filters_and_columns():
    keys = (
        akey("a", "u1", "t1", team="dev", spend=1.5),
        akey("b", "u2", "t2", team="ops", blocked=True),
    )
    rows = key_rows(state(*keys))
    assert rows == [
        {"key_alias": "a", "user_id": "u1", "team_id": "dev", "blocked": False, "spend": 1.5},
        {"key_alias": "b", "user_id": "u2", "team_id": "ops", "blocked": True, "spend": 0.0},
    ]
    assert [r["key_alias"] for r in key_rows(state(*keys), user_id="u2")] == ["b"]
    assert [r["key_alias"] for r in key_rows(state(*keys), team_id="dev")] == ["a"]


def test_block_failure_reports_keys_already_blocked(audit):
    from gatewayctl.keys import BlockError

    keys = (akey("budi-a", "budi@perusahaan.com", "tok-a"), akey("budi-b", "budi@perusahaan.com", "tok-b"))
    client = RecordingClient(fail_on_call=2)
    with pytest.raises(BlockError) as info:
        block_keys(state(*keys), client, audit, user_id="budi@perusahaan.com")
    assert info.value.blocked == ["tok-a"]
    assert info.value.target == "key:budi-b"
    assert info.value.applied is False
    assert len(audit.path.read_text(encoding="utf-8").splitlines()) == 1


def test_block_audit_failure_marks_key_as_applied(audit, monkeypatch):
    from gatewayctl.keys import BlockError

    def full_disk(self, *args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(AuditLog, "record", full_disk)
    client = RecordingClient()
    with pytest.raises(BlockError) as info:
        block_keys(state(akey("budi-a", "budi@perusahaan.com", "tok-a")), client, audit, alias="budi-a")
    assert info.value.applied is True
    assert info.value.blocked == []
    assert client.calls == [("key_block", "tok-a")]
