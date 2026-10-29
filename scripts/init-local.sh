#!/bin/sh
# Create deploy/env/local.env with random secrets. Refuses to overwrite: a new
# LITELLM_SALT_KEY would make credentials already stored in Postgres unreadable.
set -eu

ENV_FILE="deploy/env/local.env"

cd "$(dirname "$0")/.."

if [ -e "$ENV_FILE" ]; then
	echo "Gagal: $ENV_FILE sudah ada. Tidak ditimpa karena LITELLM_SALT_KEY tidak boleh diganti setelah ada data." >&2
	exit 1
fi

# hex <bytes>: random lowercase hex string of 2*bytes characters.
hex() {
	od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'
}

pg_password="$(hex 16)"

umask 077
tmp="$(mktemp "$ENV_FILE.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
{
	echo "LITELLM_MASTER_KEY=sk-$(hex 16)"
	echo "LITELLM_SALT_KEY=sk-$(hex 16)"
	echo "POSTGRES_PASSWORD=$pg_password"
	echo "REDIS_PASSWORD=$(hex 16)"
	echo "DATABASE_URL=postgresql://litellm:$pg_password@postgres:5432/litellm"
	echo "OPENAI_API_KEY=sk-mock-$(hex 8)"
	echo "OPENAI_API_BASE=http://mock-upstream:8080/v1"
} >"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$ENV_FILE"
trap - EXIT

echo "$ENV_FILE dibuat (izin 600). Simpan cadangannya: LITELLM_SALT_KEY tidak boleh hilang atau diganti."
