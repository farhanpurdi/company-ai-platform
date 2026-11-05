#!/bin/sh
# Writes a verified pg_dump of the gateway database to var/backups/ and removes
# dumps older than BACKUP_KEEP_DAYS (default 7). Stdout is only the path of the
# new dump (relative to the repo root); everything else goes to stderr, so
# `path=$(make -s backup)` works. Backups cannot be restored with another
# LITELLM_SALT_KEY: keep the env file safe next to the dumps.
# Usage: scripts/backup.sh ENV   (local | vm)
set -eu

cd "$(dirname "$0")/.."

ENV_NAME="${1:-local}"
ENV_FILE="deploy/env/$ENV_NAME.env"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
DIR="var/backups"

fail() {
	echo "backup gagal: $*" >&2
	exit 1
}

# Validate before any docker call: a retention of 0 would delete the new dump.
case "$KEEP_DAYS" in
'' | *[!0-9]*) fail "BACKUP_KEEP_DAYS harus bilangan bulat >= 1, bukan '$KEEP_DAYS'" ;;
esac
[ "$KEEP_DAYS" -ge 1 ] || fail "BACKUP_KEEP_DAYS harus bilangan bulat >= 1, bukan '$KEEP_DAYS'"

[ -f "$ENV_FILE" ] || fail "$ENV_FILE tidak ditemukan"

compose() {
	docker compose -p "llm-gateway-$ENV_NAME" -f deploy/compose.yaml -f "deploy/compose.$ENV_NAME.yaml" --env-file "$ENV_FILE" "$@"
}

umask 077
mkdir -p "$DIR"
chmod 700 "$DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
final="$DIR/litellm-$ts.dump"
partial="$DIR/.litellm-$ts.dump.partial"

# Two backups in the same second must not overwrite each other.
[ ! -e "$final" ] || fail "$final sudah ada; tunggu satu detik lalu ulangi"

trap 'rm -f "$partial"' EXIT
trap 'exit 130' INT TERM

started="$(date +%s)"

compose exec -T postgres pg_dump --format=custom -U litellm -d litellm >"$partial" ||
	fail "pg_dump gagal; stack berjalan? (make ps ENV=$ENV_NAME)"
compose exec -T postgres pg_restore --list <"$partial" >/dev/null ||
	fail "dump tidak dapat dibaca kembali oleh pg_restore; file dibuang"

mv "$partial" "$final"

# Retention runs only after the new dump is in place.
find "$DIR" -maxdepth 1 -name 'litellm-*.dump' -mmin +"$((KEEP_DAYS * 1440))" -exec rm -f {} +

bytes="$(wc -c <"$final" | tr -d ' ')"
echo "backup ok: $final ($bytes bytes, $(($(date +%s) - started)) s)" >&2
echo "$final"
