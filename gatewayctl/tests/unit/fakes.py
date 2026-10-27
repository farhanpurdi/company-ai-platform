"""Shared test doubles for apply, keys, and CLI tests."""

from gatewayctl.client import ApiError

RAW_KEY = "sk-rawsecret123456"


class RecordingClient:
    """Records mutating calls in order; the nth call (1-based) can be made to fail."""

    def __init__(self, fail_on_call: int | None = None):
        self.calls: list[tuple] = []
        self.fail_on_call = fail_on_call
        self.checked = False

    def _record(self, *call):
        self.calls.append(call)
        if self.fail_on_call == len(self.calls):
            raise ApiError(500, "/fake", "boom")

    def check(self):
        self.checked = True

    def team_new(self, payload):
        self._record("team_new", payload)
        return {}

    def team_update(self, payload):
        self._record("team_update", payload)
        return {}

    def team_delete(self, team_id):
        self._record("team_delete", team_id)

    def member_add(self, team_id, user_id, max_budget_in_team):
        self._record("member_add", team_id, user_id, max_budget_in_team)

    def member_update(self, team_id, user_id, max_budget_in_team):
        self._record("member_update", team_id, user_id, max_budget_in_team)

    def member_delete(self, team_id, user_id):
        self._record("member_delete", team_id, user_id)

    def key_generate(self, payload):
        self._record("key_generate", payload)
        return {"key": RAW_KEY, "token": "hash-new-0001"}

    def key_update(self, payload):
        self._record("key_update", payload)

    def key_block(self, token):
        self._record("key_block", token)

    def close(self):
        pass

    @property
    def names(self):
        return [c[0] for c in self.calls]
