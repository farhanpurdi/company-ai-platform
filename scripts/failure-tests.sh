#!/bin/sh
# Failure tests against the LOCAL stack: T12 (Redis down), T13 (Postgres down),
# and T15 (backup, restore). They stop Redis/Postgres for a while, so the
# script refuses any profile but local. A trap starts everything again on exit,
# failure or Ctrl+C, so a failed run never leaves the stack half dead.
# Keys are handed to pytest through the environment (-e NAME without a value),
# never on a command line.
# Usage: scripts/failure-tests.sh ENV [SCENARIO ...]   (ENV must be local)
set -eu

cd "$(dirname "$0")/.."

ENV_NAME="${1:-}"
[ "$#" -eq 0 ] || shift
ALL_SCENARIOS="t12 t13 t15"

fail() {
	echo "failure-tests gagal: $*" >&2
	exit 1
}

[ "$ENV_NAME" = "local" ] || fail "hanya untuk ENV=local (mematikan Redis/Postgres sementara); diterima '$ENV_NAME'"

SCENARIOS="${*:-$ALL_SCENARIOS}"
for s in $SCENARIOS; do
	case " $ALL_SCENARIOS " in
	*" $s "*) ;;
	*) fail "skenario '$s' tidak dikenal; pilih dari: $ALL_SCENARIOS" ;;
	esac
done

ENV_FILE="deploy/env/$ENV_NAME.env"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE tidak ditemukan"

compose() {
	docker compose -p "llm-gateway-$ENV_NAME" -f deploy/compose.yaml -f "deploy/compose.$ENV_NAME.yaml" --env-file "$ENV_FILE" "$@"
}

restore_stack() {
	status=$?
	trap - EXIT INT TERM
	compose up -d --wait redis postgres litellm-a litellm-b ||
		echo "PERINGATAN: stack tidak dapat dinyalakan lagi; jalankan: make up ENV=$ENV_NAME" >&2
	exit "$status"
}
trap restore_stack EXIT
trap 'exit 130' INT TERM

CTL="run --rm -T -e GATEWAYCTL_OPERATOR=test@local tools gatewayctl --file entitlements/$ENV_NAME.yaml"

# issue USER LABEL: prints the raw key (stdout of `key issue`); the label gets a
# per-run suffix so repeated runs never collide on the key alias.
issue() {
	compose $CTL key issue --user "$1" --label "$2-$$"
}

# phase NODE VAR...: one pytest node in the tools container; each VAR is forwarded
# from this script's environment by name only.
phase() {
	node="$1"
	shift
	flags=""
	for v in "$@"; do
		flags="$flags -e $v"
	done
	# shellcheck disable=SC2086
	compose run --rm -T $flags tools pytest -p no:cacheprovider "tests/failure/$node" -v
}

# In a fresh stack the test users exist only after entitlements are applied.
compose $CTL apply --confirm

t12() {
	T12_RPM_KEY="$(issue rate1@local.test t12-rpm)"
	T12_BUDGET_KEY="$(issue budget1@local.test t12-budget)"
	export T12_RPM_KEY T12_BUDGET_KEY
	f=test_t12_redis_down.py
	phase "$f::test_t12_prepare" T12_RPM_KEY T12_BUDGET_KEY
	compose stop redis
	phase "$f::test_t12_redis_down" T12_RPM_KEY T12_BUDGET_KEY
	compose up -d --wait redis
	phase "$f::test_t12_recovered" T12_RPM_KEY T12_BUDGET_KEY
}

t13() {
	T13_FRESH_KEY="$(issue dev2@local.test t13-fresh)"
	T13_WARM_KEY="$(issue dev2@local.test t13-warm)"
	export T13_FRESH_KEY T13_WARM_KEY
	f=test_t13_postgres_down.py
	phase "$f::test_t13_prepare" T13_FRESH_KEY T13_WARM_KEY
	compose stop postgres
	phase "$f::test_t13_postgres_down" T13_FRESH_KEY T13_WARM_KEY
	compose up -d --wait postgres
	phase "$f::test_t13_recovered" T13_FRESH_KEY T13_WARM_KEY
}

# T15: backup, then change state (a new key and its spend), restore, and check that
# the state is the one in the dump. The dump stays in var/backups/ and is removed by
# the normal retention.
t15() {
	T15_OLD_KEY="$(issue dev1@local.test t15-old)"
	T15_BUDGET_KEY="$(issue budget1@local.test t15-budget)"
	export T15_OLD_KEY T15_BUDGET_KEY
	f=test_t15_restore.py
	phase "$f::test_t15_prepare" T15_OLD_KEY T15_BUDGET_KEY
	dump="$(scripts/backup.sh "$ENV_NAME")"
	T15_NEW_KEY="$(issue dev1@local.test t15-new)"
	export T15_NEW_KEY
	phase "$f::test_t15_mutate" T15_NEW_KEY
	CONFIRM=1 scripts/restore.sh "$ENV_NAME" "$dump"
	phase "$f::test_t15_verify" T15_OLD_KEY T15_NEW_KEY T15_BUDGET_KEY
}

for s in $SCENARIOS; do
	"$s"
done
