#!/bin/sh
# PreToolUse hook (matcher Read|Edit|Write): keeps secrets out of the session and
# the gateway fail-closed (CLAUDE.md). The hook JSON arrives on stdin and is
# matched as raw text. Deny: exit 2 with the reason on stderr.
set -eu

input="$(cat)"

has() {
	printf '%s' "$input" | grep -Eq -- "$1"
}

deny() {
	echo "hook: $1" >&2
	exit 2
}

if has '"file_path" *: *"[^"]*deploy/env/[A-Za-z0-9_-]*\.env"'; then
	deny "isi deploy/env/*.env adalah rahasia (CLAUDE.md); rujuk nilainya lewat env saja"
fi

# Only the new text counts: an edit may remove a bad setting.
new_text='"(new_string|content)" *: *"([^"\\]|\\.)*'
if has '"file_path" *: *"[^"]*/deploy/[^"]*\.ya?ml"' &&
	has "${new_text}(LITELLM_LOG: *DEBUG|allow_requests_on_db_unavailable: *true|cache: *true|fail_closed_budget_enforcement: *false)"; then
	deny "gateway harus fail-closed (CLAUDE.md): tanpa LITELLM_LOG DEBUG, allow_requests_on_db_unavailable, response caching, atau fail_closed_budget_enforcement: false"
fi

exit 0
