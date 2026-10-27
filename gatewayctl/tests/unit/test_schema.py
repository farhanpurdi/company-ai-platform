import textwrap
from pathlib import Path

import pytest

from gatewayctl.schema import (
    EntitlementsError,
    GatewayConfig,
    load_entitlements,
    load_gateway_config,
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


@pytest.mark.parametrize("version", ["2", "'1'", "null"])
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
