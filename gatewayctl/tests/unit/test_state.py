from gatewayctl.model import BudgetWindow, KeyPolicy, MemberSpec, TeamSpec
from gatewayctl.state import fetch_actual, key_from_api, team_spec_from_api

MANAGED = {"managed_by": "gatewayctl"}


class FakeClient:
    """Serves fixture JSON per endpoint and records team_info calls."""

    def __init__(self, teams, infos, keys):
        self._teams, self._infos, self._keys = teams, infos, keys
        self.info_calls: list[str] = []

    def list_teams(self):
        return self._teams

    def team_info(self, team_id):
        self.info_calls.append(team_id)
        return self._infos[team_id]

    def list_keys(self):
        return self._keys


TEAM_DEV = {
    "team_id": "dev",
    "team_alias": "IT / Developer",
    "models": ["company-fast", "company-coding"],
    "max_budget": 500,
    "budget_duration": "30d",
    "rpm_limit": 600,
    "metadata": MANAGED,
}
TEAM_FOREIGN = {
    "team_id": "legacy",
    "team_alias": "Legacy",
    "models": ["company-fast"],
    "max_budget": None,
    "budget_duration": None,
    "rpm_limit": None,
    "metadata": {"owner": "someone"},
}
KEY_API = {
    "token": "hash1",
    "key_alias": "budi-laptop",
    "user_id": "budi@perusahaan.com",
    "team_id": "dev",
    "blocked": None,
    "spend": 1.25,
    "models": ["company-fast"],
    "rpm_limit": 60,
    "budget_limits": [
        {"budget_duration": "24h", "max_budget": 10},
        {"budget_duration": "30d", "max_budget": 100},
    ],
    "metadata": MANAGED,
}


def test_fetch_actual_maps_fields():
    infos = {
        "dev": {
            "team_id": "dev",
            "team_info": TEAM_DEV,
            "team_memberships": [
                {"user_id": "budi@perusahaan.com", "litellm_budget_table": {"max_budget": 100}},
                {"user_id": "sari@perusahaan.com", "litellm_budget_table": {"max_budget": 150.5}},
            ],
        }
    }
    foreign_key = {**KEY_API, "token": "hash2", "key_alias": "other", "metadata": None, "blocked": True}
    client = FakeClient([TEAM_DEV, TEAM_FOREIGN], infos, [KEY_API, foreign_key])
    actual = fetch_actual(client)

    dev = TeamSpec("dev", "IT / Developer", frozenset({"company-fast", "company-coding"}), 500.0, "30d", 600)
    assert actual.teams["dev"] == dev
    assert set(actual.teams) == {"dev", "legacy"}
    assert actual.managed_teams == frozenset({"dev"})
    assert actual.members == (
        MemberSpec("budi@perusahaan.com", "dev", 100.0),
        MemberSpec("sari@perusahaan.com", "dev", 150.5),
    )
    assert len(actual.keys) == 2
    k = actual.keys[0]
    assert k.token == "hash1"
    assert k.key_alias == "budi-laptop"
    assert k.user_id == "budi@perusahaan.com"
    assert k.team_id == "dev"
    assert k.blocked is False
    assert k.managed is True
    assert k.spend == 1.25
    assert k.policy == KeyPolicy(
        frozenset({"company-fast"}), 60, (BudgetWindow("24h", 10), BudgetWindow("30d", 100))
    )
    assert actual.keys[1].managed is False
    assert actual.keys[1].blocked is True
    # team_info only for managed teams
    assert client.info_calls == ["dev"]


def test_member_budget_from_team_info():
    infos = {
        "dev": {
            "team_info": TEAM_DEV,
            "team_memberships": [
                {"user_id": "a@x.com", "litellm_budget_table": {"max_budget": 42}},
                {"user_id": "b@x.com", "litellm_budget_table": None},
                {"user_id": "c@x.com"},
            ],
        }
    }
    actual = fetch_actual(FakeClient([TEAM_DEV], infos, []))
    budgets = {m.user_id: m.max_budget_in_team for m in actual.members}
    assert budgets == {"a@x.com": 42.0, "b@x.com": None, "c@x.com": None}
    assert all(m.team_id == "dev" for m in actual.members)


def test_members_without_membership_row_still_counted():
    # Some LiteLLM versions only create a team_membership row when a member budget is set;
    # such members appear only in members_with_roles.
    team_info = {**TEAM_DEV, "members_with_roles": [
        {"user_id": "a@x.com", "role": "user"},
        {"user_id": "svc-bot", "role": "user"},
        {"user_id": None, "role": "admin"},
    ]}
    infos = {
        "dev": {
            "team_info": team_info,
            "team_memberships": [{"user_id": "a@x.com", "litellm_budget_table": {"max_budget": 42}}],
        }
    }
    actual = fetch_actual(FakeClient([TEAM_DEV], infos, []))
    assert sorted((m.user_id, m.max_budget_in_team) for m in actual.members) == [
        ("a@x.com", 42.0),
        ("svc-bot", None),
    ]


def test_proxy_admin_member_is_ignored():
    # LiteLLM adds the caller of /team/new as team admin; with the master key that is
    # default_user_id, which no entitlements file lists, so it must not show up as a member.
    team_info = {**TEAM_DEV, "members_with_roles": [
        {"user_id": "default_user_id", "role": "admin"},
        {"user_id": "a@x.com", "role": "user"},
    ]}
    infos = {
        "dev": {
            "team_info": team_info,
            "team_memberships": [
                {"user_id": "default_user_id", "litellm_budget_table": None},
                {"user_id": "a@x.com", "litellm_budget_table": None},
            ],
        }
    }
    actual = fetch_actual(FakeClient([TEAM_DEV], infos, []))
    assert [m.user_id for m in actual.members] == ["a@x.com"]


def test_team_without_metadata_is_unmanaged():
    bare = {**TEAM_FOREIGN, "metadata": None, "team_id": "bare"}
    missing = {k: v for k, v in TEAM_FOREIGN.items() if k != "metadata"} | {"team_id": "nometa"}
    client = FakeClient([bare, missing], {}, [])
    actual = fetch_actual(client)
    assert actual.managed_teams == frozenset()
    assert set(actual.teams) == {"bare", "nometa"}
    assert actual.members == ()
    assert client.info_calls == []


def test_blocked_null_is_false():
    assert key_from_api({**KEY_API, "blocked": None}).blocked is False
    assert key_from_api({**KEY_API, "blocked": False}).blocked is False
    assert key_from_api({**KEY_API, "blocked": True}).blocked is True
    k = {key: v for key, v in KEY_API.items() if key != "blocked"}
    assert key_from_api(k).blocked is False


def test_key_from_api_tolerates_missing_optional_fields():
    k = key_from_api({"token": "t", "metadata": None})
    assert k.key_alias is None and k.user_id is None and k.team_id is None
    assert k.managed is False
    assert k.spend == 0.0
    assert k.policy == KeyPolicy(frozenset(), None, ())


def test_team_spec_from_api_defaults_for_null_limits():
    spec = team_spec_from_api(TEAM_FOREIGN)
    assert spec == TeamSpec("legacy", "Legacy", frozenset({"company-fast"}), 0.0, "", 0)
