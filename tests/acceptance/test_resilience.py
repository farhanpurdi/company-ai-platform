"""T08 (retry on upstream 429) and T09 (fallback only before the stream starts) (spec 8.2)."""

from __future__ import annotations

from helpers import chat, gateway, issue_key

TERRA = "gpt-5.6-terra"
SOL = "gpt-5.6-sol"
UPSTREAM_ATTEMPTS = 3  # 1 call + num_retries 2
MID_STREAM_PAUSE_MS = 500


def test_t08_retry_then_success(applied, mock):
    mock.scenario(TERRA, "error_429", 2)
    with gateway(issue_key("dev1@local.test")) as client:
        r = chat(client, "company-fast")
    assert r.status_code == 200, r.text
    assert len(mock.requests()) == UPSTREAM_ATTEMPTS


def test_t08_retry_exhausted(applied, mock):
    mock.scenario(TERRA, "error_429", 5)
    with gateway(issue_key("dev1@local.test")) as client:
        r = chat(client, "company-fast")
    assert r.status_code == 429, r.text
    assert len(mock.requests()) == UPSTREAM_ATTEMPTS


def test_t09_fallback_before_stream(applied, mock):
    # Every Sol attempt (call + retries) fails before the first byte.
    mock.scenario(SOL, "fail_before_stream", UPSTREAM_ATTEMPTS)
    with gateway(issue_key("dev1@local.test")) as client:
        r = chat(client, "company-reasoning", stream=True)
    models = [q["model"] for q in mock.requests()]
    print(f"T09 before-stream upstream={models}")
    assert r.status_code == 200, r.text
    assert "mock-4" in r.text
    # Sol was really tried (and failed) before the fallback to Terra answered.
    assert TERRA in models, models
    first_terra = models.index(TERRA)
    assert first_terra >= 1 and all(m == SOL for m in models[:first_terra]), models
    assert models[-1] == TERRA


def test_t09_no_fallback_mid_stream(applied, mock):
    # Sol sends two chunks, pauses, then drops the connection. Without the pause
    # the chunks can arrive together with the close and be discarded by the
    # gateway's HTTP reader, which is a failure before the stream (fallback allowed).
    mock.scenario(SOL, "fail_mid_stream", 1, delay_ms=MID_STREAM_PAUSE_MS)
    with gateway(issue_key("dev1@local.test")) as client:
        r = chat(client, "company-reasoning", stream=True)
    models = [q["model"] for q in mock.requests()]
    print(f"T09 mid-stream status={r.status_code} stream_error={r.extensions.get('stream_error')} upstream={models}")
    assert r.status_code == 200, r.text
    # The client already received Sol content, so the stream had really started.
    assert '"mock-1"' in r.text, r.text
    broken = r.extensions.get("stream_error") is not None or "[DONE]" not in r.text
    assert broken, "stream selesai normal padahal upstream putus di tengah"
    assert all(m == SOL for m in models), models
