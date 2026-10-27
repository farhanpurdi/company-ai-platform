import json
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from fakes import RAW_KEY, RecordingClient
from gatewayctl import cli
from gatewayctl.client import ApiError, GatewayUnavailable
from gatewayctl.model import ActualKey, ActualState, BudgetWindow, KeyPolicy, MemberSpec, TeamSpec
from gatewayctl.schema import load_entitlements, load_gateway_config

CONFIG = """\
model_list:
  - model_name: company-fast
  - model_name: company-coding
  - model_name: company-reasoning
router_settings:
  fallbacks:
    - company-reasoning: [company-coding]
"""

ENTITLEMENTS = """\
version: 1
teams:
  dev:
    alias: Dev
    models: [company-fast, company-coding]
    budget: {max_usd: 500, duration: 30d}
    rpm_limit: 600
    member_defaults:
      max_budget_in_team: 100
      key:
        rpm_limit: 60
        budgets: [{duration: 24h, max_usd: 10}]
    members:
      - budi@perusahaan.com
"""

INVALID = """\
version: 1
teams:
  finance:
    models: [company-fast, company-x]
    budget: {max_usd: 10, duration: 30d}
    rpm_limit: 10
"""

MASTER = "sk-master-0123456789"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def files(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    ents = tmp_path / "entitlements.yaml"
    ents.write_text(ENTITLEMENTS, encoding="utf-8")
    return config, ents


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in (
        "GATEWAYCTL_FILE",
        "LITELLM_BASE_URL",
        "LITELLM_MASTER_KEY",
        "GATEWAYCTL_OPERATOR",
        "GATEWAYCTL_AUDIT_LOG",
        "GATEWAYCTL_GIT_SHA",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GATEWAYCTL_AUDIT_LOG", str(tmp_path / "audit.log"))


@pytest.fixture
def desired(files):
    config, ents = files
    return load_entitlements(ents, load_gateway_config(config))


def synced(desired):
    return ActualState(
        teams=dict(desired.teams),
        managed_teams=frozenset(desired.teams),
        members=tuple(desired.members.values()),
        keys=(),
    )


@pytest.fixture
def backend(monkeypatch):
    """Patch the client factory and state fetch; tests set backend.actual."""

    class Backend:
        client = RecordingClient()
        actual: ActualState | None = None
        made_with: tuple | None = None

    b = Backend()

    def make_client(base_url, master_key):
        b.made_with = (base_url, master_key)
        return b.client

    monkeypatch.setattr(cli, "make_client", make_client)
    monkeypatch.setattr(cli, "fetch_actual", lambda client: b.actual)
    return b


def run(runner, files, *args, env=None):
    config, ents = files
    base = ["--file", str(ents), "--config", str(config)]
    full_env = {"LITELLM_MASTER_KEY": MASTER, "GATEWAYCTL_OPERATOR": "ops@example.com"}
    full_env.update(env or {})
    return runner.invoke(cli.app, [*base, *args], env=full_env)


def test_plan_exit_0_when_in_sync(runner, files, desired, backend):
    backend.actual = synced(desired)
    result = run(runner, files, "plan")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert backend.made_with == ("http://litellm-a:4000", MASTER)


def test_plan_exit_2_when_changes(runner, files, backend):
    backend.actual = ActualState({}, frozenset(), (), ())
    result = run(runner, files, "plan")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "+ create_team team:dev" in result.stderr
    assert "+ add_member member:dev/budi@perusahaan.com" in result.stderr


def test_plan_marks_destructive_and_lists_unmanaged(runner, files, desired, backend):
    actual = synced(desired)
    legacy = TeamSpec("legacy-x", "Legacy", frozenset(), 0.0, "", 0)
    backend.actual = ActualState(
        {**actual.teams, "legacy-x": legacy},
        actual.managed_teams,
        (*actual.members, MemberSpec("gone@perusahaan.com", "dev", None)),
        (),
    )
    result = run(runner, files, "plan")
    assert result.exit_code == 2
    assert "- remove_member member:dev/gone@perusahaan.com [destructive]" in result.stderr
    assert "team:legacy-x" in result.stderr
    assert "1 aksi" in result.stderr


def test_plan_json(runner, files, desired, backend):
    actual = synced(desired)
    legacy = TeamSpec("legacy-x", "Legacy", frozenset(), 0.0, "", 0)
    backend.actual = ActualState({**actual.teams, "legacy-x": legacy}, actual.managed_teams, actual.members, ())
    result = run(runner, files, "plan", "--json")
    assert result.exit_code == 0
    data = json.loads(result.stderr)
    assert data == {"actions": [], "unmanaged": ["team:legacy-x"], "orphan_teams": []}


def test_plan_json_action_shape(runner, files, backend):
    backend.actual = ActualState({}, frozenset(), (), ())
    data = json.loads(run(runner, files, "plan", "--json").stderr)
    first = data["actions"][0]
    assert set(first) == {"kind", "target", "before", "after", "destructive"}
    assert first["kind"] == "create_team"


def test_invalid_file_exit_1_with_path(runner, files, tmp_path, monkeypatch):
    config, _ = files
    bad = tmp_path / "bad.yaml"
    bad.write_text(INVALID, encoding="utf-8")

    def boom(*args):
        raise AssertionError("API must not be called for an invalid file")

    monkeypatch.setattr(cli, "make_client", boom)
    result = runner.invoke(
        cli.app,
        ["--file", str(bad), "--config", str(config), "plan"],
        env={"LITELLM_MASTER_KEY": MASTER},
    )
    assert result.exit_code == 1
    assert "teams.finance.models[1]" in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_file_option_exit_1(runner, files):
    config, _ = files
    result = runner.invoke(cli.app, ["--config", str(config), "plan"], env={"LITELLM_MASTER_KEY": MASTER})
    assert result.exit_code == 1
    assert "--file" in result.stderr


def test_file_from_env(runner, files, desired, backend):
    config, ents = files
    backend.actual = synced(desired)
    result = runner.invoke(
        cli.app,
        ["--config", str(config), "plan"],
        env={"LITELLM_MASTER_KEY": MASTER, "GATEWAYCTL_FILE": str(ents)},
    )
    assert result.exit_code == 0


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_master_key_exit_3_no_traceback(runner, files, monkeypatch, value):
    # Review Focus 4: empty or unset master key.
    def boom(*args):
        raise AssertionError("client must not be built without a master key")

    monkeypatch.setattr(cli, "make_client", boom)
    config, ents = files
    env = {} if value is None else {"LITELLM_MASTER_KEY": value}
    result = runner.invoke(cli.app, ["--file", str(ents), "--config", str(config), "plan"], env=env)
    assert result.exit_code == 3
    assert "LITELLM_MASTER_KEY" in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_wrong_master_key_exit_3_one_line(runner, files, backend):
    def reject():
        raise GatewayUnavailable("master key ditolak oleh LiteLLM")

    backend.client = RecordingClient()
    backend.client.check = reject
    result = run(runner, files, "plan")
    assert result.exit_code == 3
    assert len(result.stderr.strip().splitlines()) == 1
    assert "ditolak" in result.stderr
    assert "Traceback" not in result.stderr
    assert MASTER not in result.stderr + result.stdout


def test_unavailable_exit_3(runner, files, backend, monkeypatch):
    def down(client):
        raise GatewayUnavailable("tidak dapat menghubungi LiteLLM (ConnectError)")

    backend.client = RecordingClient()
    monkeypatch.setattr(cli, "fetch_actual", down)
    result = run(runner, files, "plan")
    assert result.exit_code == 3
    assert "tidak dapat menghubungi" in result.stderr
    assert "Traceback" not in result.stderr


def test_check_runs_before_fetch(runner, files, desired, backend, monkeypatch):
    backend.client = RecordingClient()
    order = []
    backend.client.check = lambda: order.append("check")
    monkeypatch.setattr(cli, "fetch_actual", lambda c: order.append("fetch") or synced(desired))
    assert run(runner, files, "plan").exit_code == 0
    assert order == ["check", "fetch"]


def test_destructive_without_confirm_exit_4_and_no_calls(runner, files, desired, backend):
    backend.client = RecordingClient()
    actual = synced(desired)
    backend.actual = ActualState(
        actual.teams,
        actual.managed_teams,
        (*actual.members, MemberSpec("gone@perusahaan.com", "dev", None)),
        (),
    )
    result = run(runner, files, "apply")
    assert result.exit_code == 4
    assert backend.client.calls == []
    assert "--confirm" in result.stderr
    assert "remove_member" in result.stderr
    assert not Path(cli_audit_path()).exists()


def cli_audit_path():
    import os

    return os.environ["GATEWAYCTL_AUDIT_LOG"]


def test_apply_with_confirm_executes_and_audits(runner, files, desired, backend):
    backend.client = RecordingClient()
    actual = synced(desired)
    backend.actual = ActualState(
        actual.teams,
        actual.managed_teams,
        (*actual.members, MemberSpec("gone@perusahaan.com", "dev", None)),
        (),
    )
    result = run(runner, files, "apply", "--confirm", env={"GATEWAYCTL_GIT_SHA": "deadbeef"})
    assert result.exit_code == 0, result.stderr
    assert backend.client.calls == [("member_delete", "dev", "gone@perusahaan.com")]
    entry = json.loads(Path(cli_audit_path()).read_text(encoding="utf-8").splitlines()[0])
    assert entry["operator"] == "ops@example.com"
    assert entry["git_sha"] == "deadbeef"
    assert entry["action"] == "remove_member"


def test_apply_nondestructive_needs_no_confirm(runner, files, backend):
    backend.client = RecordingClient()
    backend.actual = ActualState({}, frozenset(), (), ())
    result = run(runner, files, "apply")
    assert result.exit_code == 0, result.stderr
    assert backend.client.names == ["team_new", "member_add"]


def test_apply_in_sync_does_nothing(runner, files, desired, backend):
    backend.client = RecordingClient()
    backend.actual = synced(desired)
    result = run(runner, files, "apply")
    assert result.exit_code == 0
    assert backend.client.calls == []


def test_apply_failure_exit_1(runner, files, backend):
    backend.client = RecordingClient(fail_on_call=2)
    backend.actual = ActualState({}, frozenset(), (), ())
    result = run(runner, files, "apply")
    assert result.exit_code == 1
    assert "member:dev/budi@perusahaan.com" in result.stderr
    assert "Traceback" not in result.stderr
    assert len(Path(cli_audit_path()).read_text(encoding="utf-8").splitlines()) == 1


def test_apply_requires_operator(runner, files, backend):
    backend.client = RecordingClient()
    backend.actual = ActualState({}, frozenset(), (), ())
    config, ents = files
    result = runner.invoke(
        cli.app,
        ["--file", str(ents), "--config", str(config), "apply"],
        env={"LITELLM_MASTER_KEY": MASTER},
    )
    assert result.exit_code == 1
    assert "GATEWAYCTL_OPERATOR" in result.stderr
    assert backend.client.calls == []


def test_apply_prune_passed_to_diff(runner, files, desired, backend):
    backend.client = RecordingClient()
    actual = synced(desired)
    orphan = TeamSpec("old", "Old", frozenset({"company-fast"}), 1.0, "30d", 1)
    backend.actual = ActualState(
        {**actual.teams, "old": orphan}, actual.managed_teams | {"old"}, actual.members, ()
    )
    plan = run(runner, files, "plan")
    assert plan.exit_code == 0
    assert "old" in plan.stderr  # orphan listed
    applied = run(runner, files, "apply", "--confirm", "--prune")
    assert applied.exit_code == 0, applied.stderr
    assert backend.client.names == ["team_delete"]


def test_conflict_error_exit_1(runner, files, desired, backend):
    actual = synced(desired)
    backend.actual = ActualState(actual.teams, frozenset(), (), ())  # 'dev' exists but unmanaged
    result = run(runner, files, "plan")
    assert result.exit_code == 1
    assert "dev" in result.stderr
    assert "Traceback" not in result.stderr


def test_key_issue_stdout_is_only_the_key(runner, files, desired, backend):
    # Review Focus 5.
    backend.client = RecordingClient()
    backend.actual = synced(desired)
    result = run(runner, files, "key", "issue", "--user", "Budi@Perusahaan.com ", "--label", "opencode")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == RAW_KEY + "\n"
    assert RAW_KEY not in result.stderr
    assert backend.client.calls[0][1]["key_alias"] == "budi@perusahaan.com-opencode"
    assert RAW_KEY not in Path(cli_audit_path()).read_text(encoding="utf-8")


def test_key_issue_alias_exists_exit_1(runner, files, desired, backend):
    backend.client = RecordingClient()
    existing = ActualKey(
        "tok1",
        "budi@perusahaan.com-opencode",
        "budi@perusahaan.com",
        "dev",
        False,
        KeyPolicy(frozenset(), None, ()),
        True,
    )
    actual = synced(desired)
    backend.actual = ActualState(actual.teams, actual.managed_teams, actual.members, (existing,))
    result = run(runner, files, "key", "issue", "--user", "budi@perusahaan.com", "--label", "opencode")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "budi@perusahaan.com-opencode" in result.stderr
    assert backend.client.calls == []


def test_key_issue_unknown_user_exit_1(runner, files, desired, backend):
    backend.client = RecordingClient()
    backend.actual = synced(desired)
    result = run(runner, files, "key", "issue", "--user", "nobody@x.com", "--label", "a")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert backend.client.calls == []


def test_key_issue_requires_operator_and_args(runner, files, desired, backend):
    backend.client = RecordingClient()
    backend.actual = synced(desired)
    config, ents = files
    base = ["--file", str(ents), "--config", str(config), "key", "issue"]
    no_op = runner.invoke(
        cli.app, [*base, "--user", "budi@perusahaan.com", "--label", "a"], env={"LITELLM_MASTER_KEY": MASTER}
    )
    assert no_op.exit_code == 1 and "GATEWAYCTL_OPERATOR" in no_op.stderr
    no_label = run(runner, files, "key", "issue", "--user", "budi@perusahaan.com")
    assert no_label.exit_code == 1
    assert backend.client.calls == []


def _actual_with_keys(desired):
    policy = KeyPolicy(frozenset({"company-fast"}), 60, (BudgetWindow("24h", 10),))
    keys = (
        ActualKey("tok-a", "budi-a", "budi@perusahaan.com", "dev", False, policy, True, 1.25),
        ActualKey("tok-b", "sari-a", "sari@perusahaan.com", "ops", False, policy, True, 0.0),
    )
    actual = synced(desired)
    return ActualState(actual.teams, actual.managed_teams, actual.members, keys)


def test_key_block_by_user(runner, files, desired, backend):
    backend.client = RecordingClient()
    backend.actual = _actual_with_keys(desired)
    result = run(runner, files, "key", "block", "--user", "Budi@Perusahaan.com")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert backend.client.calls == [("key_block", "tok-a")]


def test_key_block_by_alias(runner, files, desired, backend):
    backend.client = RecordingClient()
    backend.actual = _actual_with_keys(desired)
    result = run(runner, files, "key", "block", "--alias", "sari-a")
    assert result.exit_code == 0
    assert backend.client.calls == [("key_block", "tok-b")]


def test_key_block_needs_exactly_one_selector_and_operator(runner, files, desired, backend):
    backend.client = RecordingClient()
    backend.actual = _actual_with_keys(desired)
    assert run(runner, files, "key", "block").exit_code == 1
    assert run(runner, files, "key", "block", "--user", "a", "--alias", "b").exit_code == 1
    config, ents = files
    no_op = runner.invoke(
        cli.app,
        ["--file", str(ents), "--config", str(config), "key", "block", "--alias", "sari-a"],
        env={"LITELLM_MASTER_KEY": MASTER},
    )
    assert no_op.exit_code == 1
    assert backend.client.calls == []


def test_key_block_nothing_to_block_exit_1(runner, files, desired, backend):
    backend.client = RecordingClient()
    backend.actual = _actual_with_keys(desired)
    result = run(runner, files, "key", "block", "--alias", "missing")
    assert result.exit_code == 1


def test_key_list_filters_without_raw_keys(runner, files, desired, backend):
    backend.actual = _actual_with_keys(desired)
    result = run(runner, files, "key", "list", "--team", "dev")
    assert result.exit_code == 0
    assert "budi-a" in result.stderr
    assert "sari-a" not in result.stderr
    assert "tok-a" not in result.stderr
    assert result.stdout == ""


# --- Real LiteLLMClient through respx: error-to-exit-code mapping (spec 6.7) ---

BASE = "http://litellm-a:4000"
COMMANDS = [
    ["plan"],
    ["apply"],
    ["key", "list"],
    ["key", "block", "--alias", "x"],
    ["key", "issue", "--user", "budi@perusahaan.com", "--label", "a"],
]


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def assert_clean_failure(result, code):
    assert result.exit_code == code, result.stderr
    assert len(result.stderr.strip().splitlines()) == 1
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert MASTER not in result.stderr


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("status", [401, 403])
def test_http_rejected_master_key_exit_3(runner, files, api, command, status):
    api.get("/key/list").respond(status, text="denied")
    assert_clean_failure(run(runner, files, *command), 3)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("status", [500, 502, 503])
def test_http_5xx_on_check_exit_3(runner, files, api, command, status):
    api.get("/key/list").respond(status, text="<html>\nbad gateway " + MASTER + "\n</html>")
    result = run(runner, files, *command)
    assert_clean_failure(result, 3)
    assert str(status) in result.stderr


@pytest.mark.parametrize("command", COMMANDS)
def test_http_other_4xx_on_check_exit_1(runner, files, api, command):
    api.get("/key/list").respond(400, text="bad request")
    assert_clean_failure(run(runner, files, *command), 1)


@pytest.mark.parametrize("command", COMMANDS)
def test_connect_error_exit_3(runner, files, api, command):
    api.get("/key/list").mock(side_effect=httpx.ConnectError("refused"))
    assert_clean_failure(run(runner, files, *command), 3)


def test_malformed_json_in_state_exit_1(runner, files, api):
    api.get("/key/list").respond(200, json={"keys": []})
    api.get("/team/list").respond(200, text="<html>not json</html>")
    assert_clean_failure(run(runner, files, "plan"), 1)


def test_unexpected_shape_in_state_exit_1(runner, files, api):
    api.get("/key/list").respond(200, json={"keys": []})
    api.get("/team/list").respond(200, json=[{"no_team_id": True}])
    assert_clean_failure(run(runner, files, "plan"), 1)


def test_api_error_while_fetching_state_exit_1(runner, files, api):
    api.get("/key/list").respond(200, json={"keys": []})
    api.get("/team/list").respond(500, text="boom")
    assert_clean_failure(run(runner, files, "plan"), 1)


def test_unavailable_mid_apply_is_apply_failure_exit_1(runner, files, backend):
    # Spec 6.7: an API failure in the middle of apply is exit 1, even if it is a connection loss.
    class Dropping(RecordingClient):
        def team_new(self, payload):
            raise GatewayUnavailable("tidak dapat menghubungi LiteLLM (ReadError)")

    backend.client = Dropping()
    backend.actual = ActualState({}, frozenset(), (), ())
    result = run(runner, files, "apply")
    assert result.exit_code == 1
    assert "team:dev" in result.stderr
    assert "Traceback" not in result.stderr


# --- Unwritable audit log (spec 6.6): fail before any mutation, one line ---


@pytest.fixture
def broken_audit(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    return {"GATEWAYCTL_AUDIT_LOG": str(blocker / "audit.log")}


def test_apply_with_unwritable_audit_fails_before_mutating(runner, files, backend, broken_audit):
    backend.client = RecordingClient()
    backend.actual = ActualState({}, frozenset(), (), ())
    result = run(runner, files, "apply", env=broken_audit)
    # apply prints the plan first, so only the last line is the error.
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "audit log tidak dapat ditulis" in result.stderr.strip().splitlines()[-1]
    assert backend.client.calls == []


def test_key_issue_with_unwritable_audit_does_not_generate(runner, files, desired, backend, broken_audit):
    backend.client = RecordingClient()
    backend.actual = synced(desired)
    result = run(
        runner, files, "key", "issue", "--user", "budi@perusahaan.com", "--label", "a", env=broken_audit
    )
    assert_clean_failure(result, 1)
    assert "audit" in result.stderr
    assert backend.client.calls == []


def test_key_block_with_unwritable_audit_does_not_block(runner, files, desired, backend, broken_audit):
    backend.client = RecordingClient()
    backend.actual = _actual_with_keys(desired)
    result = run(runner, files, "key", "block", "--alias", "sari-a", env=broken_audit)
    assert_clean_failure(result, 1)
    assert backend.client.calls == []


def test_key_issue_audit_failing_after_generate_names_alias_and_hides_key(
    runner, files, desired, backend, monkeypatch
):
    backend.client = RecordingClient()
    backend.actual = synced(desired)

    def full_disk(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cli.AuditLog, "record", full_disk)
    result = run(runner, files, "key", "issue", "--user", "budi@perusahaan.com", "--label", "a")
    assert_clean_failure(result, 1)
    assert "budi@perusahaan.com-a" in result.stderr
    assert RAW_KEY not in result.stderr
