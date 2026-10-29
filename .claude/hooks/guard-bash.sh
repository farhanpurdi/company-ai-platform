#!/bin/sh
# PreToolUse hook (matcher Bash): stops CLAUDE.md violations before the command
# runs, also in unattended workflow and /goal runs. The hook JSON arrives on
# stdin and is matched as raw text, so the host needs no jq or Python.
# Deny: exit 2 with the reason on stderr. Ask: permissionDecision JSON on stdout.
set -eu

input="$(cat)"

has() {
	printf '%s' "$input" | grep -Eq -- "$1"
}

deny() {
	echo "hook: $1" >&2
	exit 2
}

ask() {
	printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}\n' "$1"
	exit 0
}

# Volumes hold keys, teams and spend. Throwaway verify projects are the exception.
if has '(down[^|;&]*(-v|--volumes)([ "]|$)|docker volume (rm|prune))' && ! has 'llm-gateway-(vmverify|cfgcheck)'; then
	deny "menghapus volume Docker dilarang (CLAUDE.md): key, team, dan spend ikut hilang"
fi

if has 'git( -C [^ ]+)? commit[^|;&]*(--no-verify|[ ]-[A-Za-z]*n[A-Za-z]*([ "]|$))'; then
	deny "commit tanpa hook pre-commit dilarang (CLAUDE.md); perbaiki penyebab hook gagal"
fi

# A verb that prints or sources an env file, in the same command segment as its path.
if has '(^|[^A-Za-z_-])(cat|less|more|head|tail|grep|egrep|sed|awk|source|strings|xxd|od)( [^|;&]*)? [^ |;&"]*deploy/env/[A-Za-z0-9_-]*\.env([^.A-Za-z0-9_]|$)'; then
	deny "isi deploy/env/*.env adalah rahasia (CLAUDE.md); rujuk nilainya lewat env saja"
fi

# Setting it (start of a command, after export/env or other assignments, or a
# container -e flag); merely naming it, e.g. in a commit message, is fine.
if has '("command" *: *"|[;&|(]|\\n) *(export +|env +)?([A-Za-z_][A-Za-z0-9_]*=[^ ]* +)*LITELLM_LOG=DEBUG|(-e|--env)[ =]LITELLM_LOG=DEBUG'; then
	deny "LITELLM_LOG=DEBUG mencetak isi request ke log (CLAUDE.md)"
fi

# Acceptance tests share mock, budget and rate-limit state.
if has '(make[^|;&]* test([ "]|$)|pytest[^|;&]*tests/acceptance)' && pgrep -f 'tests/integration tests/acceptance' >/dev/null 2>&1; then
	deny "uji acceptance lain masih berjalan; jangan menjalankan dua make test bersamaan (CLAUDE.md)"
fi

if has 'git( -C [^ ]+)? push([ "]|$)'; then
	ask "git push butuh izin pemilik repo (CLAUDE.md)"
fi

exit 0
