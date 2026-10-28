#!/bin/sh
# T10 (spec 8.2): search every gateway container log and the LiteLLM_SpendLogs
# table for the sentinel values written by tests/acceptance/test_log_hygiene.py
# plus LITELLM_MASTER_KEY and OPENAI_API_KEY from the env file. mock-upstream is
# excluded: it receives prompts by design. Prints only source names, never values.
# Before grepping it checks that the T10 traffic actually reached the spend log
# and the Caddy access log, so a clean result is not just an empty source.
# Usage: scripts/t10-scan-logs.sh ENV   (local | vm)
set -eu

cd "$(dirname "$0")/.."

ENV_NAME="${1:-local}"
ENV_FILE="deploy/env/$ENV_NAME.env"
SENTINELS="var/t10-sentinels.txt"
SERVICES="litellm-a litellm-b caddy postgres redis"
T10_REQUESTS=2
SPEND_WAIT_S="${T10_SPEND_WAIT_S:-60}"

fail() {
	echo "T10 gagal: $*" >&2
	exit 1
}

case "$SPEND_WAIT_S" in
'' | *[!0-9]*) fail "T10_SPEND_WAIT_S harus bilangan bulat detik (mis. 120), bukan '$SPEND_WAIT_S'" ;;
esac

[ -f "$ENV_FILE" ] || fail "$ENV_FILE tidak ditemukan"
[ -s "$SENTINELS" ] || fail "$SENTINELS kosong atau tidak ada; jalankan tests/acceptance/test_log_hygiene.py dulu"

compose() {
	docker compose -p "llm-gateway-$ENV_NAME" -f deploy/compose.yaml -f "deploy/compose.$ENV_NAME.yaml" --env-file "$ENV_FILE" "$@"
}

# env_value NAME: last NAME=... value in the env file, without surrounding quotes.
env_value() {
	sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | sed -e 's/\r$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
trap 'exit 130' INT TERM

# Patterns live in a private temp file, never on a command line or in output.
grep -v '^[[:space:]]*$' "$SENTINELS" >"$work/patterns" || fail "$SENTINELS tidak berisi nilai penanda"
for name in LITELLM_MASTER_KEY OPENAI_API_KEY; do
	value="$(env_value "$name")"
	[ -n "$value" ] || fail "$name kosong di $ENV_FILE"
	printf '%s\n' "$value" >>"$work/patterns"
done

sha256() {
	if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1
}

# LiteLLM keys spend log rows by sha256 of the raw key. The raw key only goes
# through a pipe; its hash is not secret.
grep -q '^sk-' "$SENTINELS" || fail "$SENTINELS tidak berisi key T10"
key_hash="$(grep '^sk-' "$SENTINELS" | head -n 1 | tr -d '\n' | sha256)"
waited=0
while :; do
	rows="$(echo "SELECT count(*) FROM \"LiteLLM_SpendLogs\" WHERE api_key = :'h';" |
		compose exec -T postgres psql -U litellm -d litellm -X -At -v ON_ERROR_STOP=1 -v h="$key_hash" 2>/dev/null)" ||
		fail "tabel LiteLLM_SpendLogs tidak dapat dibaca"
	[ "$rows" -ge "$T10_REQUESTS" ] && break
	[ "$waited" -ge "$SPEND_WAIT_S" ] &&
		fail "LiteLLM_SpendLogs hanya berisi $rows dari $T10_REQUESTS request T10 setelah $SPEND_WAIT_S detik"
	sleep 2
	waited=$((waited + 2))
done

found=""
for svc in $SERVICES; do
	compose logs --no-color "$svc" >"$work/log" 2>&1 || fail "log $svc tidak dapat dibaca"
	if grep -qF -f "$work/patterns" "$work/log"; then
		found="$found $svc"
	fi
	if [ "$svc" = caddy ] && ! grep -qF '"uri":"/v1/chat/completions"' "$work/log"; then
		fail "access log Caddy tidak berisi request /v1/chat/completions"
	fi
done

compose exec -T postgres psql -U litellm -d litellm -X -q -v ON_ERROR_STOP=1 \
	-c 'COPY (SELECT * FROM "LiteLLM_SpendLogs") TO STDOUT' >"$work/spendlogs" 2>&1 ||
	fail "tabel LiteLLM_SpendLogs tidak dapat dibaca"
if grep -qF -f "$work/patterns" "$work/spendlogs"; then
	found="$found postgres:LiteLLM_SpendLogs"
fi

if [ -n "$found" ]; then
	echo "T10 GAGAL: nilai penanda atau rahasia ditemukan di:$found" >&2
	exit 1
fi
echo "T10 clean ($(wc -l <"$work/patterns" | tr -d ' ') nilai, sumber: $SERVICES postgres:LiteLLM_SpendLogs)"
