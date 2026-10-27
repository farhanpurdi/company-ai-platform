import textwrap
from pathlib import Path

import pytest

from gatewayctl.schema import (
    EntitlementsError,
    GatewayConfig,
    load_entitlements,
    load_gateway_config,
    normalize_id,
)
from gatewayctl.model import BudgetWindow, KeyPolicy, MemberSpec, TeamSpec

CONFIG = """\
model_list: [{model_name: company-fast}, {model_name: company-coding}, {model_name: company-reasoning}]
router_settings: {fallbacks: [{"company-reasoning": ["company-coding"]}]}
"""

# Spec section 6.1, verbatim.
SPEC_EXAMPLE = """\
version: 1
teams:
  it-developer:
    alias: "IT / Developer"
    models: [company-fast, company-coding, company-reasoning]
    budget: { max_usd: 500, duration: 30d }
    rpm_limit: 600
    member_defaults:
      max_budget_in_team: 100
      key:
        rpm_limit: 60
        budgets: [{ duration: 24h, max_usd: 10 }, { duration: 30d, max_usd: 100 }]
    members:
      - budi@perusahaan.com
      - { user_id: sari@perusahaan.com, max_budget_in_team: 150 }
service_accounts:
  svc-helpdesk-bot:
    team: it-developer
    models: [company-fast]
    rpm_limit: 120
    budgets: [{ duration: 30d, max_usd: 50 }]
"""

ALL = frozenset({"company-fast", "company-coding", "company-reasoning"})


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "entitlements.yaml"
    path.write_text(textwrap.dedent(text))
    return path


@pytest.fixture
def config(tmp_path: Path) -> GatewayConfig:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG)
    return load_gateway_config(path)


def load_error(tmp_path: Path, text: str, config: GatewayConfig) -> EntitlementsError:
    with pytest.raises(EntitlementsError) as exc:
        load_entitlements(write(tmp_path, text), config)
    return exc.value


def test_load_gateway_config_reads_aliases_and_fallbacks(config):
    assert config.aliases == ALL
    assert dict(config.fallbacks) == {"company-reasoning": ("company-coding",)}


def test_spec_example_resolves(tmp_path, config):
    s = load_entitlements(write(tmp_path, SPEC_EXAMPLE), config)
    assert s.teams["it-developer"] == TeamSpec(
        "it-developer", "IT / Developer", ALL, 500, "30d", 600
    )
    assert s.members["budi@perusahaan.com"] == MemberSpec(
        "budi@perusahaan.com", "it-developer", 100
    )
    assert s.members["sari@perusahaan.com"].max_budget_in_team == 150
    assert s.key_policies["budi@perusahaan.com"] == KeyPolicy(
        ALL, 60, (BudgetWindow("24h", 10), BudgetWindow("30d", 100))
    )
    assert s.members["svc-helpdesk-bot"] == MemberSpec(
        "svc-helpdesk-bot", "it-developer", None, "service_account"
    )
    assert s.key_policies["svc-helpdesk-bot"] == KeyPolicy(
        frozenset({"company-fast"}), 120, (BudgetWindow("30d", 50),)
    )


def test_member_key_override_merges_fieldwise(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              qa:
                models: [company-fast, company-coding]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                member_defaults:
                  max_budget_in_team: 5
                  key:
                    models: [company-fast]
                    rpm_limit: 60
                    budgets: [{ duration: 24h, max_usd: 10 }]
                members:
                  - { user_id: rate1@x.test, key: { rpm_limit: 3 } }
            """,
        ),
        config,
    )
    assert s.key_policies["rate1@x.test"] == KeyPolicy(
        frozenset({"company-fast"}), 3, (BudgetWindow("24h", 10),)
    )
    assert s.members["rate1@x.test"] == MemberSpec("rate1@x.test", "qa", 5)


def test_team_alias_defaults_to_team_id(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              finance:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
            """,
        ),
        config,
    )
    assert s.teams["finance"].alias == "finance"
    assert s.members == {} and s.key_policies == {}


def test_empty_members_and_service_accounts_allowed(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              finance:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                members:
            service_accounts:
            """,
        ),
        config,
    )
    assert list(s.teams) == ["finance"] and s.members == {}


def test_unknown_alias(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          finance:
            models: [company-fast, company-x]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
        """,
        config,
    )
    assert err.path == "teams.finance.models[1]" and "company-x" in err.message
    assert str(err) == "teams.finance.models[1]: alias 'company-x' tidak ada di config.yaml"


def test_key_models_not_subset(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          finance:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members:
              - { user_id: fin1@x.test, key: { models: [company-coding] } }
        """,
        config,
    )
    assert err.path == "teams.finance.members[0].key.models"
    assert "company-coding" in err.message


def test_member_defaults_key_models_not_subset(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          finance:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            member_defaults:
              key: { models: [company-coding] }
        """,
        config,
    )
    assert err.path == "teams.finance.member_defaults.key.models"


def test_service_account_models_not_subset(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          finance:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
        service_accounts:
          svc:
            team: finance
            models: [company-reasoning]
        """,
        config,
    )
    assert err.path == "service_accounts.svc.models"
    assert "company-reasoning" in err.message


def test_fallback_target_missing(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          x:
            models: [company-fast, company-reasoning]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
        """,
        config,
    )
    assert err.path == "teams.x.models" and "company-coding" in err.message


def test_user_in_two_teams(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members: [dup@x.test]
          b:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members: [dup@x.test]
        """,
        config,
    )
    assert err.path == "teams.b.members[0]" and "dup@x.test" in err.message


def test_service_account_collides_with_user(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members: [budi@perusahaan.com]
        service_accounts:
          budi@perusahaan.com:
            team: a
        """,
        config,
    )
    assert err.path == "service_accounts.budi@perusahaan.com"


def test_service_account_unknown_team(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
        service_accounts:
          svc:
            team: nope
        """,
        config,
    )
    assert err.path == "service_accounts.svc.team" and "nope" in err.message


# Review Focus 1: member ids are case- and whitespace-insensitive.
def test_member_ids_normalized(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              a:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                members:
                  - "  Budi@Perusahaan.com "
                  - { user_id: " Sari@Perusahaan.COM", max_budget_in_team: 3 }
            """,
        ),
        config,
    )
    assert set(s.members) == {"budi@perusahaan.com", "sari@perusahaan.com"}
    assert s.members["budi@perusahaan.com"].user_id == "budi@perusahaan.com"
    assert set(s.key_policies) == {"budi@perusahaan.com", "sari@perusahaan.com"}


def test_member_ids_normalized_duplicate_across_teams(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members: ["  Budi@Perusahaan.com "]
          b:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members: [budi@perusahaan.com]
        """,
        config,
    )
    assert err.path == "teams.b.members[0]" and "budi@perusahaan.com" in err.message


def test_member_ids_normalized_duplicate_in_same_team(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members: [budi@perusahaan.com, { user_id: " BUDI@perusahaan.com" }]
        """,
        config,
    )
    assert err.path == "teams.a.members[1]" and "budi@perusahaan.com" in err.message


def test_member_entry_must_be_string_or_mapping(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            members: [[budi@perusahaan.com]]
        """,
        config,
    )
    assert err.path == "teams.a.members[0]" and "user_id" in err.message


@pytest.mark.parametrize("team_id", ["IT Dev", "-ops", "Finance", "a_b"])
def test_team_id_format(tmp_path, config, team_id):
    err = load_error(
        tmp_path,
        f"""\
        version: 1
        teams:
          "{team_id}":
            models: [company-fast]
            budget: {{ max_usd: 10, duration: 30d }}
            rpm_limit: 100
        """,
        config,
    )
    assert err.path == f"teams.{team_id}"
    assert "^[a-z0-9][a-z0-9-]*$" in err.message


@pytest.mark.parametrize(
    "team_duration, key_duration, path",
    [
        ("1 week", "24h", "teams.a.budget.duration"),
        ("30d", "1 week", "teams.a.member_defaults.key.budgets[0].duration"),
        ("30", "24h", "teams.a.budget.duration"),
    ],
)
def test_budget_duration_format(tmp_path, config, team_duration, key_duration, path):
    err = load_error(
        tmp_path,
        f"""\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: {{ max_usd: 10, duration: "{team_duration}" }}
            rpm_limit: 100
            member_defaults:
              key: {{ budgets: [{{ duration: "{key_duration}", max_usd: 1 }}] }}
        """,
        config,
    )
    assert err.path == path
    assert r"^\d+[hd]$" in err.message


@pytest.mark.parametrize(
    "team_duration, key_duration, path",
    [
        ("0d", "24h", "teams.a.budget.duration"),
        ("30d", "0h", "teams.a.member_defaults.key.budgets[0].duration"),
    ],
)
def test_zero_budget_duration_rejected(tmp_path, config, team_duration, key_duration, path):
    err = load_error(
        tmp_path,
        f"""\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: {{ max_usd: 10, duration: {team_duration} }}
            rpm_limit: 100
            member_defaults:
              key: {{ budgets: [{{ duration: {key_duration}, max_usd: 1 }}] }}
        """,
        config,
    )
    assert err.path == path and "lebih dari 0" in err.message


@pytest.mark.parametrize(
    "budgets_owner, path",
    [
        (
            "member_defaults: { key: { budgets: [B1, B2] } }",
            "teams.a.member_defaults.key.budgets[1].duration",
        ),
        (
            "members: [{ user_id: u@x.test, key: { budgets: [B1, B2] } }]",
            "teams.a.members[0].key.budgets[1].duration",
        ),
    ],
)
def test_repeated_budget_duration_rejected(tmp_path, config, budgets_owner, path):
    owner = budgets_owner.replace("B1", "{ duration: 24h, max_usd: 1 }").replace(
        "B2", "{ duration: 1d, max_usd: 2 }"
    )
    err = load_error(
        tmp_path,
        f"""\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: {{ max_usd: 10, duration: 30d }}
            rpm_limit: 100
            {owner}
        """,
        config,
    )
    assert err.path == path and "1d" in err.message


def test_service_account_repeated_budget_duration_rejected(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
        service_accounts:
          svc:
            team: a
            budgets: [{ duration: 30d, max_usd: 1 }, { duration: 30d, max_usd: 2 }]
        """,
        config,
    )
    assert err.path == "service_accounts.svc.budgets[1].duration"


# A null in a member override (e.g. list items commented out) must inherit the
# defaults rather than drop a limit; only an explicit [] clears budgets.
def test_null_in_member_override_inherits_defaults(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              a:
                models: [company-fast, company-coding]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                member_defaults:
                  max_budget_in_team: 5
                  key:
                    models: [company-fast]
                    rpm_limit: 60
                    budgets: [{ duration: 24h, max_usd: 10 }]
                members:
                  - user_id: n1@x.test
                    max_budget_in_team:
                    key:
                      models:
                      rpm_limit: null
                      budgets:
                  - { user_id: n2@x.test, key: { budgets: [] } }
            """,
        ),
        config,
    )
    defaults = KeyPolicy(frozenset({"company-fast"}), 60, (BudgetWindow("24h", 10),))
    assert s.key_policies["n1@x.test"] == defaults
    assert s.members["n1@x.test"].max_budget_in_team == 5
    assert s.key_policies["n2@x.test"] == KeyPolicy(frozenset({"company-fast"}), 60, ())


@pytest.mark.parametrize("version", ["2", "'1'", "null", "true", "1.0"])
def test_version_must_be_1(tmp_path, config, version):
    err = load_error(tmp_path, f"version: {version}\nteams: {{}}\n", config)
    assert err.path == "version"


def test_missing_version(tmp_path, config):
    err = load_error(tmp_path, "teams: {}\n", config)
    assert err.path == "version"


def test_unknown_field_rejected(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
            rpm_limt: 5
        """,
        config,
    )
    assert err.path == "teams.a.rpm_limt"


def test_missing_file_is_entitlements_error(tmp_path, config):
    with pytest.raises(EntitlementsError) as exc:
        load_entitlements(tmp_path / "missing.yaml", config)
    assert exc.value.path == str(tmp_path / "missing.yaml")


def test_root_must_be_mapping(tmp_path, config):
    err = load_error(tmp_path, "- version\n", config)
    assert err.path == str(tmp_path / "entitlements.yaml")


def test_invalid_yaml_is_entitlements_error(tmp_path, config):
    err = load_error(tmp_path, "version: 1\nteams: {a: [\n", config)
    assert err.path == str(tmp_path / "entitlements.yaml")


def test_gateway_config_without_model_list_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("router_settings: {}\n")
    with pytest.raises(EntitlementsError) as exc:
        load_gateway_config(path)
    assert exc.value.path == str(path)


# YAML true/yes and quoted numbers must not be coerced into limits.
@pytest.mark.parametrize(
    "team_rpm, max_usd, key_rpm, path, message",
    [
        ("true", "10", "60", "teams.a.rpm_limit", "bilangan bulat"),
        ('"600"', "10", "60", "teams.a.rpm_limit", "bilangan bulat"),
        ("600", "yes", "60", "teams.a.budget.max_usd", "angka"),
        ("600", '"10"', "60", "teams.a.budget.max_usd", "angka"),
        ("600", "10", "on", "teams.a.member_defaults.key.rpm_limit", "bilangan bulat"),
        ("600", "10", "60.0", "teams.a.member_defaults.key.rpm_limit", "bilangan bulat"),
    ],
)
def test_numbers_are_not_coerced(tmp_path, config, team_rpm, max_usd, key_rpm, path, message):
    err = load_error(
        tmp_path,
        f"""\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: {{ max_usd: {max_usd}, duration: 30d }}
            rpm_limit: {team_rpm}
            member_defaults:
              key: {{ rpm_limit: {key_rpm} }}
        """,
        config,
    )
    assert err.path == path and message in err.message


def test_integer_usd_still_accepted(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              a:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                member_defaults: { max_budget_in_team: 2.5 }
                members: [u@x.test]
            """,
        ),
        config,
    )
    assert s.teams["a"].max_budget == 10.0
    assert s.members["u@x.test"].max_budget_in_team == 2.5


# Review Focus 1: ids carry no inner spaces or invisible characters.
@pytest.mark.parametrize(
    "member", ['"budi @x.test"', '"budi@x.test\\u200b"', '{ user_id: "budi\\t@x.test" }']
)
def test_user_id_with_inner_whitespace_rejected(tmp_path, config, member):
    err = load_error(
        tmp_path,
        f"""\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: {{ max_usd: 10, duration: 30d }}
            rpm_limit: 100
            members: [{member}]
        """,
        config,
    )
    assert err.path == "teams.a.members[0].user_id"
    assert "spasi atau karakter tak terlihat" in err.message


def test_service_account_name_with_inner_whitespace_rejected(tmp_path, config):
    err = load_error(
        tmp_path,
        """\
        version: 1
        teams:
          a:
            models: [company-fast]
            budget: { max_usd: 10, duration: 30d }
            rpm_limit: 100
        service_accounts:
          "svc bot":
            team: a
        """,
        config,
    )
    assert err.path == "service_accounts.svc bot"
    assert "spasi atau karakter tak terlihat" in err.message


def test_normalize_id_is_public():
    assert normalize_id("  Budi@Perusahaan.COM ") == "budi@perusahaan.com"


@pytest.mark.parametrize("key", ["2024", "yes", "~"])
def test_non_string_team_key_rejected(tmp_path, config, key):
    err = load_error(
        tmp_path,
        f"""\
        version: 1
        teams:
          {key}:
            models: [company-fast]
            budget: {{ max_usd: 10, duration: 30d }}
            rpm_limit: 100
        """,
        config,
    )
    assert err.path == "teams" and "tanda kutip" in err.message


def test_quoted_numeric_team_key_accepted(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              "2024":
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
            """,
        ),
        config,
    )
    assert list(s.teams) == ["2024"]


@pytest.mark.parametrize(
    "text, path",
    [
        ("version: 1\n1: x\n", None),
        (
            "version: 1\nteams:\n  a:\n    models: [company-fast]\n"
            "    budget: { max_usd: 10, duration: 30d }\n    rpm_limit: 100\n    1: x\n",
            "teams.a",
        ),
    ],
)
def test_non_string_field_key_rejected(tmp_path, config, text, path):
    err = load_error(tmp_path, text, config)
    assert err.path == (path or str(tmp_path / "entitlements.yaml"))
    assert "tanda kutip" in err.message


# A repeated key would otherwise keep only the last block, silently dropping
# members (offboarding them on the next apply) or whole teams.
@pytest.mark.parametrize(
    "text, key, line, first_line, parent",
    [
        (
            """\
            version: 1
            teams:
              a:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                members: [u1@x.test, u2@x.test]
              a:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                members: [u3@x.test]
            """,
            "a",
            8,
            3,
            "teams",
        ),
        (
            """\
            version: 1
            teams:
              a:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
            teams:
              b:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
            """,
            "teams",
            7,
            2,
            None,
        ),
        (
            """\
            version: 1
            teams:
              a:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
            service_accounts:
              svc: { team: a, rpm_limit: 5 }
              svc: { team: a, rpm_limit: 50 }
            """,
            "svc",
            9,
            8,
            "service_accounts",
        ),
        (
            """\
            version: 1
            teams:
              a:
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
                members: [{ user_id: a@x.test, user_id: b@x.test }]
            """,
            "user_id",
            7,
            7,
            "teams.a.members[0]",
        ),
    ],
    ids=["team", "root", "service-account", "user-id"],
)
def test_duplicate_yaml_key_rejected(tmp_path, config, text, key, line, first_line, parent):
    err = load_error(tmp_path, text, config)
    assert err.path == str(tmp_path / "entitlements.yaml")
    assert f"kunci duplikat '{key}'" in err.message
    assert f"pertama ditulis di baris {first_line}" in err.message
    assert f"(baris {line}," in err.message
    if parent:
        assert f" di {parent}," in err.message


def test_merge_key_override_is_not_a_duplicate(tmp_path, config):
    s = load_entitlements(
        write(
            tmp_path,
            """\
            version: 1
            teams:
              a: &team
                models: [company-fast]
                budget: { max_usd: 10, duration: 30d }
                rpm_limit: 100
              b:
                <<: *team
                rpm_limit: 50
            """,
        ),
        config,
    )
    assert s.teams["a"].rpm_limit == 100 and s.teams["b"].rpm_limit == 50


def test_gateway_config_duplicate_key_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "model_list: [{model_name: company-fast}]\nmodel_list: [{model_name: company-x}]\n"
    )
    with pytest.raises(EntitlementsError) as exc:
        load_gateway_config(path)
    assert exc.value.path == str(path) and "kunci duplikat 'model_list'" in exc.value.message


def test_non_utf8_file_is_entitlements_error(tmp_path, config):
    path = tmp_path / "entitlements.yaml"
    path.write_bytes(b"\xff\xfev\x00e\x00r\x00")
    with pytest.raises(EntitlementsError) as exc:
        load_entitlements(path, config)
    assert exc.value.path == str(path) and "UTF-8" in exc.value.message


def test_repo_entitlements_load_with_placeholders_uncommented(tmp_path):
    # The pilot.yaml header says members are added by uncommenting a line.
    repo = Path(__file__).resolve().parents[3]
    gateway = load_gateway_config(repo / "deploy" / "litellm" / "config.yaml")
    for name in ("local.yaml", "pilot.yaml"):
        load_entitlements(repo / "entitlements" / name, gateway)
    text = (repo / "entitlements" / "pilot.yaml").read_text(encoding="utf-8")
    uncommented = text.replace("# - nama.depan@perusahaan.com", "- nama.depan@perusahaan.com", 1)
    uncommented = uncommented.replace(
        "# - nama.depan@perusahaan.com", "- nama.belakang@perusahaan.com", 1
    )
    assert uncommented.count("nama.") == 2
    path = tmp_path / "pilot.yaml"
    path.write_text(uncommented, encoding="utf-8")
    desired = load_entitlements(path, gateway)
    assert desired.members["nama.depan@perusahaan.com"].team_id == "it-developer"
    assert desired.members["nama.belakang@perusahaan.com"].team_id == "finance"
