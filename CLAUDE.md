# LiteLLM Pilot Gateway

Repo pilot gateway LLM internal berbasis LiteLLM Proxy (Fase 0–1). Sumber kebenaran:

- Spec: `docs/superpowers/specs/2026-10-27-litellm-pilot-design.md`
- Plan implementasi: `docs/superpowers/plans/2026-10-27-litellm-pilot.md`
- Spec Fase 2: `docs/superpowers/specs/2026-11-04-fase2-vm-production-design.md`
- Plan Fase 2: `docs/superpowers/plans/2026-11-04-fase2-vm-production.md`
- Konteks fase dan gate: `docs/LITELLM_IMPLEMENTATION_GUIDE.md`, `docs/LLM_GATEWAY_ARCHITECTURE.md`

Bila kode dan spec berbeda, tanyakan dulu. Jangan mengubah diam-diam perilaku yang dikunci spec.

## Larangan

- Jangan mencetak, menulis ke file, atau meng-commit nilai `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `OPENAI_API_KEY`, password Postgres/Redis, atau virtual key mentah. Rujuk lewat env saja.
- `deploy/env/*.env` (kecuali `*.env.example`), `var/`, dan `deploy/certs/` tidak pernah di-commit.
- `LITELLM_SALT_KEY` tidak boleh diganti setelah ada data: kredensial di DB tidak bisa didekripsi lagi. `make init-local` sengaja menolak menimpa `deploy/env/local.env`.
- Gateway harus fail-closed: jangan aktifkan `allow_requests_on_db_unavailable`, jangan nyalakan response caching, jangan set `LITELLM_LOG=DEBUG` (mencetak body request), dan jangan matikan `fail_closed_budget_enforcement` (tanpa flag itu, request paralel melewati budget).
- Jangan menulis langsung ke tabel Postgres LiteLLM; perubahan lewat management API.
- Jangan `docker compose down -v` atau menghapus volume tanpa diminta: key, team, dan spend ikut hilang.
- Jangan `make restore` di VM tanpa diminta pemilik repo: isi database diganti isi dump.

## Cara kerja

- Team, member, budget, dan izin alias diubah di `entitlements/*.yaml`, lalu `make plan` dan `make apply`. Jangan memakai `curl` manual ke management API untuk itu.
- Semua tool Python berjalan di container `tools`; host cukup Docker dan make. Jangan memasang dependensi ke host.
- Aktifkan hook pre-commit sekali per clone dengan `make hooks`. Hook menolak file env/`var/`/`deploy/certs/`, key mentah, dan skrip shell yang rusak, lalu menjalankan `make unit`. Jangan melewatinya dengan `--no-verify`.
- `make unit` tidak butuh stack. `make test` butuh stack lokal hidup (`make up`; `make init-local` hanya sekali).
- Uji acceptance berbagi state stack (mock, budget, rate limit): jangan menjalankan dua `make test` bersamaan.
- `make test-failure` (T12, T13, T15) hanya untuk stack lokal dan mematikan Redis/Postgres sementara. `make loadtest` (T16) memakai mock. Jangan jalankan `make test`, `make test-failure`, dan `make loadtest` bersamaan.
- Ambang T03 (overshoot ≤ 10%), T09 (tanpa fallback di tengah stream), T13 (key yang di-cache ditolak ≤ 300 detik), dan T16 (0 error, selisih p95 token pertama ≤ 1 detik) tidak boleh dilonggarkan, di-skip, atau di-xfail. Kegagalan asli dilaporkan sebagai temuan Gate 2.
- `gatewayctl` hanya menulis key mentah dari `key issue` ke stdout; semua output lain, termasuk `plan --json` dan `key list`, ke stderr. Script dan test yang mem-parse output harus membaca stderr.

## Konvensi

- `docs/*.md` dan pesan CLI untuk operator dalam bahasa Indonesia; identifier dan komentar kode dalam bahasa Inggris.
- Kerja di branch fitur dengan commit kecil per task. Jangan push tanpa izin pemilik repo.
