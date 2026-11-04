#!/bin/sh
# Replaces the gateway database with a dump made by scripts/backup.sh.
# Order: check the dump, stop both replicas, pg_restore in ONE transaction (a
# failure leaves the old database intact), flush Redis (budget and rate-limit
# counters must be rebuilt from the restored spend), start the replicas.
# If the restore fails the replicas stay stopped: nothing half-restored is served.
# Usage: CONFIRM=1 scripts/restore.sh ENV BACKUP_PATH
set -eu

cd "$(dirname "$0")/.."

ENV_NAME="${1:-local}"
BACKUP="${2:-}"
ENV_FILE="deploy/env/$ENV_NAME.env"

fail() {
	echo "restore gagal: $*" >&2
	exit 1
}

[ -n "$BACKUP" ] || fail "path backup wajib: make restore BACKUP=var/backups/litellm-<waktu>.dump CONFIRM=1"
[ -f "$BACKUP" ] || fail "$BACKUP tidak ditemukan"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE tidak ditemukan"

if [ "${CONFIRM:-}" != "1" ]; then
	cat >&2 <<EOF
restore belum dijalankan: ini mengganti SELURUH isi database profil '$ENV_NAME' dengan isi $BACKUP.
Langkah yang akan dijalankan:
  1. periksa dump dengan pg_restore --list
  2. hentikan litellm-a dan litellm-b
  3. pg_restore dalam satu transaksi (gagal = database lama utuh)
  4. kosongkan Redis (FLUSHALL)
  5. nyalakan litellm-a dan litellm-b
Peringatan: LITELLM_SALT_KEY di $ENV_FILE harus sama dengan saat backup dibuat,
kalau tidak kredensial di database tidak dapat didekripsi.
Ulangi dengan CONFIRM=1 untuk melanjutkan.
EOF
	exit 1
fi

compose() {
	docker compose -p "llm-gateway-$ENV_NAME" -f deploy/compose.yaml -f "deploy/compose.$ENV_NAME.yaml" --env-file "$ENV_FILE" "$@"
}

compose exec -T postgres pg_restore --list <"$BACKUP" >/dev/null ||
	fail "$BACKUP tidak dapat dibaca oleh pg_restore; tidak ada yang dihentikan"

compose stop litellm-a litellm-b || fail "replika tidak dapat dihentikan"

if ! compose exec -T postgres pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error -U litellm -d litellm <"$BACKUP"; then
	fail "database tidak berubah (single transaction). Replika tetap mati. Nyalakan lagi dengan data lama: make up ENV=$ENV_NAME, atau ulangi restore dengan dump lain."
fi

# Password is expanded inside the container, never on the host command line.
compose exec -T redis sh -c 'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" FLUSHALL' >/dev/null ||
	fail "database sudah dipulihkan tetapi Redis gagal dikosongkan. Replika tetap mati; kosongkan Redis lalu: make up ENV=$ENV_NAME"

compose up -d --wait litellm-a litellm-b || fail "database sudah dipulihkan tetapi replika tidak sehat; periksa: make ps ENV=$ENV_NAME"

echo "restore ok: $BACKUP -> profil $ENV_NAME" >&2
