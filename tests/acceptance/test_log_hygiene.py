"""T10: sentinel traffic for the log scan in scripts/t10-scan-logs.sh (spec 8.2).

The test sends a sentinel prompt with a fresh key and records both values in
var/t10-sentinels.txt; `make test` then greps every container log and the
LiteLLM_SpendLogs table for them. The key is blocked once the traffic is done,
so the value left in var/ (gitignored, mode 600) no longer grants access.
"""

from __future__ import annotations

import hashlib
import os
import uuid

from helpers import REPO, admin, chat, gateway, issue_key, run_ctl

SENTINELS_FILE = REPO / "var" / "t10-sentinels.txt"


def _auth_hash(token: str) -> str:
    # Same digest the mock records for the Authorization header it receives.
    return hashlib.sha256(f"Bearer {token}".encode()).hexdigest()[:16]


def _write_sentinels(values: list[str]) -> None:
    SENTINELS_FILE.parent.mkdir(exist_ok=True)
    fd = os.open(SENTINELS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(f"{v}\n" for v in values))
    os.chmod(SENTINELS_FILE, 0o600)


def test_t10_traffic_with_sentinels(applied, mock):
    prompt = f"SENTINEL-PROMPT-{uuid.uuid4()}"
    key = issue_key("dev1@local.test")
    alias = admin().key_info(key)["info"]["key_alias"]
    _write_sentinels([prompt, key])
    try:
        with gateway(key) as client:
            streamed = chat(client, "company-fast", stream=True, prompt=prompt)
            plain = chat(client, "company-fast", prompt=prompt)
    finally:
        block = run_ctl("key", "block", "--alias", alias)
    assert streamed.status_code == 200, streamed.text
    assert "[DONE]" in streamed.text
    assert plain.status_code == 200, plain.text
    assert block.returncode == 0, block.stderr

    seen = mock.requests()
    assert len(seen) == 2
    upstream_hash = _auth_hash(os.environ["OPENAI_API_KEY"])
    for q in seen:
        # The gateway swaps the virtual key for the provider key.
        assert q["auth_hash"] == upstream_hash
        assert q["auth_hash"] != _auth_hash(key)
