# Implementasi: Fase 2, produksi di VM pilot

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VM pilot siap dipakai 20–50 pengguna: backup dan restore Postgres, metrik Prometheus untuk DevOps, uji T12/T13/T15/T16, dan dokumen Gate 3.

**Architecture:** Skrip POSIX sh di host (`scripts/backup.sh`, `scripts/restore.sh`, `scripts/failure-tests.sh`) mengatur container lewat `docker compose`, mengikuti pola `scripts/t10-scan-logs.sh`. Pytest tetap berjalan di container `tools`. Untuk uji yang mematikan container, skrip host menjalankan pytest per fase dan meneruskan key lewat environment. LiteLLM membuka `/metrics` lewat callback Prometheus, dan DevOps memakai key service account `prometheus` ber-budget $0.

**Tech Stack:** Docker Compose v2, GNU Make, POSIX sh, Python 3.12 dengan pytest dan httpx (di container `tools`), PostgreSQL 16 (`pg_dump`/`pg_restore` di container `postgres`), Redis 7, LiteLLM `v1.106.4` yang dipin ke digest.

**Spec:** `docs/superpowers/specs/2026-11-04-fase2-vm-production-design.md`

## Global Constraints

- Gateway tetap fail-closed: tanpa `allow_requests_on_db_unavailable`, tanpa response caching, tanpa `LITELLM_LOG=DEBUG`, dan `fail_closed_budget_enforcement: true` tidak diubah.
- `require_auth_for_metrics_endpoint` tidak diset `false`. Master key tidak pernah diberikan ke DevOps.
- Service account scraper persis: `prometheus`, `team: it-developer`, `models: [company-fast]`, `rpm_limit: 10`, `budgets: [{ duration: 30d, max_usd: 0 }]`, di `entitlements/pilot.yaml` dan `entitlements/local.yaml`.
- Backup: folder `var/backups/` (izin 700), file `litellm-<YYYYMMDDTHHMMSSZ>.dump` (UTC, izin 600), retensi `BACKUP_KEEP_DAYS` default 7, cron `15 2 * * *`.
- `make test-failure` hanya untuk `ENV=local`. `make restore` wajib `CONFIRM=1` dan tidak dijalankan di VM tanpa permintaan pemilik repo.
- Ambang T13 (key yang di-cache ditolak ≤ 300 detik; pulih ≤ 120 detik), T12 (pulih ≤ 120 detik), dan T16 (0 error; selisih p95 waktu token pertama ≤ 1 detik pada 25 dan 50 stream bersamaan) tidak dilonggarkan, tidak di-skip, dan tidak di-xfail. T03 dan T09 tidak disentuh. Kegagalan asli dilaporkan sebagai temuan Gate 3.
- Key mentah tidak ditulis ke file. Antarlangkah, key diteruskan lewat environment seperti `SMOKE_KEY`. Satu-satunya pengecualian yang sudah ada adalah `var/t10-sentinels.txt`.
- Python hanya di container `tools`. Host cukup Docker, make, dan POSIX sh.
- `docs/*.md` dan pesan untuk operator dalam bahasa Indonesia; identifier dan komentar kode dalam bahasa Inggris.
- Branch `feat/fase2-vm-production` dari `main` setelah PR spec dan plan ini di-merge. Satu commit per task, selalu lewat hook pre-commit (tanpa `--no-verify`). Push hanya dengan izin pemilik repo.
- `make test`, `make test-failure`, dan `make loadtest` berbagi state stack lokal: jangan dijalankan bersamaan.
- Jangan pernah `docker compose down -v`.
- File yang tidak boleh diubah: kedua spec, `docs/LLM_GATEWAY_ARCHITECTURE.md`, plan pilot, dan `docs/LITELLM_IMPLEMENTATION_GUIDE.md` kecuali dua baris di Task 9.

## Review Focus

1. **`BACKUP_KEEP_DAYS=0` atau bukan angka.** Retensi 0 akan menghapus dump yang baru saja dibuat. Skrip harus menolak nilai selain bilangan bulat ≥ 1, sebelum dump dibuat. Ditangkap oleh `test_rejects_bad_keep_days` (Task 2).
2. **Dua backup dalam detik yang sama**, misalnya cron dan backup manual bersamaan. File yang sudah ada tidak boleh tertimpa. Ditangkap oleh `test_refuses_to_overwrite_existing_dump` (Task 2).
3. **`make restore` tanpa `BACKUP` atau dengan path yang salah.** Tidak boleh ada container yang dihentikan. Ditangkap oleh `test_missing_backup_stops_nothing` (Task 3).
4. **Restore gagal di tengah jalan.** Replika tidak boleh dinyalakan ke database setengah jadi. Restore berjalan dalam satu transaksi, jadi database lama utuh, dan operator diberi tahu cara menyalakan lagi. Ditangkap oleh `test_failed_restore_keeps_replicas_stopped` (Task 3).
5. **Uji kegagalan terputus** (gagal atau Ctrl+C) sehingga Redis atau Postgres tertinggal mati. `trap` harus menyalakan semuanya lagi. Ditangkap oleh `test_restarts_services_when_a_phase_fails` (Task 6).

## Struktur file

| File | Aksi | Task |
| --- | --- | --- |
| `.claude/hooks/guard-bash.sh`, `deploy/tests/test_claude_hooks.py`, `CLAUDE.md` | Ubah | 1 |
| `scripts/backup.sh`, `deploy/tests/test_backup_script.py` | Buat | 2 |
| `scripts/restore.sh`, `deploy/tests/test_restore_script.py` | Buat | 3 |
| `Makefile`, `deploy/tests/test_makefile.py` | Ubah | 2, 3, 6, 8 |
| `deploy/litellm/config.yaml`, `deploy/tests/test_litellm_config.py` | Ubah | 4 |
| `entitlements/pilot.yaml`, `entitlements/local.yaml` | Ubah | 4 (scraper), 8 (`qa-load`) |
| `deploy/tests/test_entitlements_scraper.py`, `tests/integration/test_metrics.py` | Buat | 4 |
| `scripts/t10-scan-logs.sh`, `deploy/tests/test_t10_scan.py` | Ubah | 5 |
| `scripts/failure-tests.sh`, `deploy/tests/test_failure_tests_script.py`, `tests/failure/test_t12_redis_down.py`, `tests/failure/test_t13_postgres_down.py` | Buat | 6 |
| `tests/failure/test_t15_restore.py` | Buat | 7 |
| `scripts/failure-tests.sh` | Ubah (skenario `t15`) | 7 |
| `tests/load/test_t16_load.py` | Buat | 8 |
| `docs/devops-handoff.md`, `docs/gate3-checklist.md` | Buat | 9 |
| `docs/operator-guide.md`, `docs/setup-admin.md`, `docs/LITELLM_IMPLEMENTATION_GUIDE.md` (dua baris), `deploy/tests/test_docs_access.py` | Ubah | 9 |

Urutan: Task 1 → 2 → 3 → 4 → 5 → 6 → 7 (butuh 2, 3, 6) → 8 → 9 (butuh nama metrik dari 4 dan semua target make) → 10.

## Kesepakatan bersama skrip host

Semua skrip baru mendefinisikan `compose()` persis seperti `scripts/t10-scan-logs.sh`:

```sh
compose() {
	docker compose -p "llm-gateway-$ENV_NAME" -f deploy/compose.yaml -f "deploy/compose.$ENV_NAME.yaml" --env-file "$ENV_FILE" "$@"
}
```

Uji unit memakai stub `docker` di `PATH`, mengikuti pola `deploy/tests/test_t10_scan.py`. Stub menulis setiap pemanggilan (`$*`) sebagai satu baris ke `$STUB_DIR/calls`, lalu menjawab berdasarkan pola argumen. File penanda di `$STUB_DIR` (misalnya `dump_fail`) membuat langkah tertentu gagal. Perintah yang dicocokkan stub, dan karena itu wajib dipakai persis oleh skrip:

| Langkah | Argumen setelah `compose` |
| --- | --- |
| Dump | `exec -T postgres pg_dump --format=custom -U litellm -d litellm` |
| Cek dump (stdin) | `exec -T postgres pg_restore --list` |
| Hentikan replika | `stop litellm-a litellm-b` |
| Restore (stdin) | `exec -T postgres pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error -U litellm -d litellm` |
| Kosongkan Redis | `exec -T redis sh -c 'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" FLUSHALL'` |
| Nyalakan replika | `up -d --wait litellm-a litellm-b` |
| Hentikan/nyalakan layanan uji | `stop redis`, `up -d --wait redis`, `stop postgres`, `up -d --wait postgres` |
| pytest satu fase | `run --rm -T <env flags> tools pytest -p no:cacheprovider <node id> -v` |
| Terapkan entitlements | `run --rm -T -e GATEWAYCTL_OPERATOR=test@local tools gatewayctl --file entitlements/local.yaml apply --confirm` |
| Terbitkan key | `run --rm -T -e GATEWAYCTL_OPERATOR=test@local tools gatewayctl --file entitlements/local.yaml key issue --user <user> --label <label>` |

Password Redis hanya diekspansi di dalam container (`$REDIS_PASSWORD` dalam kutip tunggal). Skrip tidak membaca nilai rahasia dari env file.

---

### Task 1: Aturan Fase 2 di `CLAUDE.md` dan hook penjaga

**Files:**
- Modify: `CLAUDE.md`, `.claude/hooks/guard-bash.sh`
- Test: `deploy/tests/test_claude_hooks.py`

**Interfaces:**
- Produces: hook meminta izin (`ask`) untuk `make ... restore ... ENV=vm` dan `scripts/restore.sh vm`. Pemeriksaan "uji lain masih berjalan" juga berlaku untuk `make test-failure`, `make loadtest`, dan pytest di `tests/failure` atau `tests/load`.

- [ ] **Step 1: Tulis uji yang gagal di `deploy/tests/test_claude_hooks.py`**

```python
ASK_BASH = [
    "make restore ENV=vm BACKUP=var/backups/x.dump CONFIRM=1",
    "CONFIRM=1 scripts/restore.sh vm var/backups/x.dump",
]

@pytest.mark.parametrize("cmd", ASK_BASH)
def test_restore_on_vm_asks_owner(cmd):
    r = _run("guard-bash.sh", {"command": cmd})
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
```

Tambahkan ke `ALLOW_BASH`: `"make restore BACKUP=var/backups/x.dump CONFIRM=1"` (profil lokal), `"make test-failure"`, `"make loadtest"`, `"make backup ENV=vm"`. Uji `test_bash_guard_allows` yang sudah ada menuntut keluaran kosong dan exit 0.

- [ ] **Step 2: Jalankan `make unit`.** Harapan: `test_restore_on_vm_asks_owner` FAIL (stdout kosong).

- [ ] **Step 3: Ubah `.claude/hooks/guard-bash.sh`**
  - Sebelum pemeriksaan `git push`, tambahkan `ask` bila `has '(make[^|;&]* restore[^|;&]*ENV=vm|restore\.sh +vm([ "]|$))'`. Alasannya: `"make restore di VM mengganti isi database produksi; butuh izin pemilik repo (CLAUDE.md)"`.
  - Perluas pola perintah di pemeriksaan concurrency menjadi `(make[^|;&]* (test|test-failure|loadtest)([ "]|$)|pytest[^|;&]*tests/(acceptance|failure|load))`.
  - Perluas pola `pgrep -f` menjadi `'tests/integration tests/acceptance|failure-tests\.sh|tests/failure|tests/load'`.

- [ ] **Step 4: Ubah `CLAUDE.md`**
  - Sumber kebenaran: tambahkan `docs/superpowers/specs/2026-11-04-fase2-vm-production-design.md` dan plan ini.
  - Larangan: "Jangan `make restore` di VM tanpa diminta pemilik repo: isi database diganti isi dump."
  - Cara kerja: "`make test-failure` (T12, T13, T15) hanya untuk stack lokal dan mematikan Redis/Postgres sementara. `make loadtest` (T16) memakai mock. Jangan jalankan `make test`, `make test-failure`, dan `make loadtest` bersamaan."
  - Baris ambang: ubah menjadi "Ambang T03 (overshoot ≤ 10%), T09 (tanpa fallback di tengah stream), T13 (key yang di-cache ditolak ≤ 300 detik), dan T16 (0 error, selisih p95 token pertama ≤ 1 detik) tidak boleh dilonggarkan, di-skip, atau di-xfail."

- [ ] **Step 5: Jalankan `make unit`.** Harapan: semua PASS.

- [ ] **Step 6: Commit** `feat: Fase 2 rules in CLAUDE.md and hook guards for restore and failure tests`

---

### Task 2: `make backup`

**Files:**
- Create: `scripts/backup.sh` (executable), `deploy/tests/test_backup_script.py`
- Modify: `Makefile`, `deploy/tests/test_makefile.py`

**Interfaces:**
- Produces: `scripts/backup.sh ENV`. Stdout hanya berisi path dump baru, relatif ke root repo (`var/backups/litellm-<ts>.dump`). Stderr berisi satu baris ringkasan `backup ok: <path> (<bytes> bytes, <detik> s)`. Exit 0 bila berhasil, 1 bila gagal. Env `BACKUP_KEEP_DAYS` (default 7). Target make `backup:` dengan resep `@scripts/backup.sh $(ENV)`.

- [ ] **Step 1: Tulis uji yang gagal di `deploy/tests/test_backup_script.py`**

Fixture `repo(tmp_path)` menyalin skrip, membuat `deploy/env/local.env` palsu, dan memasang stub `docker`:

```sh
#!/bin/sh
echo "$*" >>"$STUB_DIR/calls"
case "$*" in
  *" pg_dump "*) [ -f "$STUB_DIR/dump_fail" ] && exit 1; printf 'PGDMP-fake' ;;
  *" pg_restore --list"*) cat >/dev/null; [ -f "$STUB_DIR/list_fail" ] && exit 1; echo ';toc' ;;
  *) echo "stub docker: unexpected $*" >&2; exit 9 ;;
esac
```

Uji yang ditulis:
- `test_backup_writes_private_dump`: exit 0. Stdout cocok dengan `^var/backups/litellm-\d{8}T\d{6}Z\.dump$`. File berisi `PGDMP-fake` dengan izin `0o600`, folder `0o700`, dan tidak ada file `.partial`.
- `test_unreadable_dump_leaves_no_file` (`list_fail`) dan `test_failed_pg_dump_leaves_no_file` (`dump_fail`): exit 1, stdout kosong, tidak ada `*.dump` maupun `.partial`.
- `test_retention_deletes_only_old_dumps`: siapkan `litellm-old.dump` dengan mtime 8 hari lalu, `litellm-recent.dump` 6 hari lalu, dan `backup.log` 30 hari lalu. Setelah backup berhasil, hanya `litellm-old.dump` yang hilang.
- `test_retention_skipped_when_backup_fails`: kondisi sama ditambah `dump_fail`. Ketiga file tetap ada.
- `test_rejects_bad_keep_days` (parametrize `"0"`, `"abc"`, `"-1"`): exit 1 dan `calls` kosong.
- `test_refuses_to_overwrite_existing_dump`: stub `date` di `PATH` selalu mencetak `20261104T021500Z`. Buat `var/backups/litellm-20261104T021500Z.dump` berisi `old`. Hasilnya exit 1, isi file tetap `old`.
- `test_stdout_is_only_the_path`: stdout tepat satu baris.

Di `deploy/tests/test_makefile.py`: `test_backup_target_is_silent_and_calls_script`. Resep `backup` berisi `scripts/backup.sh $(ENV)` dan setiap barisnya diawali `@`, supaya `$(make -s backup)` hanya menangkap path.

- [ ] **Step 2: Jalankan `make unit`.** Harapan: FAIL karena skrip dan target belum ada.

- [ ] **Step 3: Tulis `scripts/backup.sh`**

Validasi `BACKUP_KEEP_DAYS` (bilangan bulat ≥ 1) dilakukan sebelum `docker` dipanggil. Gunakan `umask 077`, `mkdir -p var/backups && chmod 700 var/backups`, dan nama `ts="$(date -u +%Y%m%dT%H%M%SZ)"`. Tolak bila `var/backups/litellm-$ts.dump` sudah ada.

Dump ditulis ke `var/backups/.litellm-$ts.dump.partial`. `trap` menghapus file `.partial` saat keluar. Cek dengan `pg_restore --list < partial`, lalu `mv` ke nama akhir. Retensi: `find var/backups -maxdepth 1 -name 'litellm-*.dump' -mmin +$((BACKUP_KEEP_DAYS * 1440)) -exec rm -f {} +`, hanya setelah `mv` berhasil.

Pesan error untuk operator dalam bahasa Indonesia, diawali `backup gagal: `.

- [ ] **Step 4: Tambahkan target `backup` ke `Makefile`** (dan ke `.PHONY`), dengan komentar bahwa stdout hanya berisi path.

- [ ] **Step 5: Jalankan `make unit`.** Harapan: PASS.

- [ ] **Step 6: Verifikasi di stack lokal**

Jalankan `make up` lalu `make -s backup`. Harapan: satu path tercetak, `ls -l var/backups` menampilkan `-rw-------`, dan `docker compose ... exec -T postgres pg_restore --list < <path> | head -3` menampilkan TOC.

- [ ] **Step 7: Commit** `feat: make backup writes a verified pg_dump to var/backups with retention`

---

### Task 3: `make restore`

**Files:**
- Create: `scripts/restore.sh` (executable), `deploy/tests/test_restore_script.py`
- Modify: `Makefile`, `deploy/tests/test_makefile.py`

**Interfaces:**
- Consumes: format dump dari Task 2.
- Produces: `CONFIRM=1 scripts/restore.sh ENV BACKUP_PATH`, exit 0 bila berhasil dan 1 bila gagal atau tidak dikonfirmasi. Target make `restore:` dengan resep `CONFIRM="$(CONFIRM)" scripts/restore.sh $(ENV) "$(BACKUP)"`.

- [ ] **Step 1: Tulis uji yang gagal di `deploy/tests/test_restore_script.py`**

Stub `docker` sama dengan Task 2, ditambah cabang `*" stop "*`, `*" up -d --wait "*`, dan `*"FLUSHALL"*` (exit 0). Cabang restore: `*" pg_restore --clean"*` membaca stdin, lalu exit 1 bila ada `restore_fail`. Cabang `pg_restore --list` diletakkan setelah cabang `--clean`. Env file palsu berisi `REDIS_PASSWORD=fake-redis-pass-123`.

Uji yang ditulis:
- `test_requires_confirm`: tanpa `CONFIRM`. Hasilnya exit 1, stderr memuat `CONFIRM=1` dan nama file, `calls` kosong.
- `test_missing_backup_stops_nothing` (parametrize path `""` dan `var/backups/nope.dump`, dengan `CONFIRM=1`): exit 1, `calls` kosong.
- `test_unreadable_dump_stops_nothing` (`list_fail`): exit 1, `calls` hanya berisi baris `pg_restore --list`.
- `test_restore_runs_in_order`: urutan baris `calls` cocok dengan list, stop, `pg_restore --clean ...`, `FLUSHALL`, `up -d --wait litellm-a litellm-b`. Hasilnya exit 0.
- `test_failed_restore_keeps_replicas_stopped` (`restore_fail`): exit 1, tidak ada baris `up -d`, stderr memuat `make up`.
- `test_no_secret_on_command_line`: `fake-redis-pass-123` tidak ada di `calls`.

Di `deploy/tests/test_makefile.py`: `test_restore_target_passes_confirm_and_backup`. Resepnya memuat `CONFIRM="$(CONFIRM)"`, `scripts/restore.sh $(ENV)`, dan `"$(BACKUP)"`.

- [ ] **Step 2: Jalankan `make unit`.** Harapan: FAIL.

- [ ] **Step 3: Tulis `scripts/restore.sh`**

Urutan pemeriksaan:
1. Argumen dan file ada.
2. `CONFIRM=1`. Bila tidak, cetak rencana lalu exit 1: profil, file, dan langkah 3–6 spec 4.3, ditambah peringatan bahwa `LITELLM_SALT_KEY` harus sama dengan saat backup.
3. `pg_restore --list`.

Lalu jalankan perintah tabel "Kesepakatan bersama" sesuai urutan uji. Bila `pg_restore --clean` gagal, cetak `restore gagal: database tidak berubah (single transaction). Replika tetap mati. Nyalakan lagi dengan data lama: make up ENV=<env>, atau ulangi restore dengan dump lain.` lalu exit 1.

- [ ] **Step 4: Tambahkan target `restore` ke `Makefile` dan `.PHONY`.**

- [ ] **Step 5: Jalankan `make unit`.** Harapan: PASS.

- [ ] **Step 6: Commit** `feat: make restore replaces the database from a dump, single transaction, CONFIRM=1`

Restore ujung-ke-ujung terhadap stack sungguhan diuji di Task 7 (T15).

---

### Task 4: Metrik Prometheus dan key scraper

**Files:**
- Modify: `deploy/litellm/config.yaml`, `deploy/tests/test_litellm_config.py`, `entitlements/pilot.yaml`, `entitlements/local.yaml`
- Create: `deploy/tests/test_entitlements_scraper.py`, `tests/integration/test_metrics.py`

**Interfaces:**
- Produces: `/metrics` di `litellm-a` dan `litellm-b`, dan service account `prometheus`. Task 9 memakai daftar nama metrik yang dicatat di Step 7.

- [ ] **Step 1: Tulis uji unit yang gagal**

Di `deploy/tests/test_litellm_config.py`:

```python
def test_prometheus_metrics_enabled():
    s = _config()["litellm_settings"]
    assert s.get("callbacks") == ["prometheus"]
    assert s.get("service_callback") == ["prometheus_system"]

def test_metrics_endpoint_keeps_auth():
    s = _config()["litellm_settings"]
    assert s.get("require_auth_for_metrics_endpoint", True) is not False
```

Di `deploy/tests/test_entitlements_scraper.py`, parametrize `entitlements/pilot.yaml` dan `entitlements/local.yaml`:

```python
assert doc["service_accounts"]["prometheus"] == {
    "team": "it-developer", "models": ["company-fast"], "rpm_limit": 10,
    "budgets": [{"duration": "30d", "max_usd": 0}],
}
```

- [ ] **Step 2: Jalankan `make unit`.** Harapan: FAIL.

- [ ] **Step 3: Ubah config dan entitlements**
  - Tambahkan kedua kunci di `litellm_settings`, dengan komentar: metrik dibaca Prometheus DevOps (spec Fase 2 bagian 5), dan autentikasi `/metrics` tetap menyala.
  - Tambahkan blok `service_accounts.prometheus` ke `entitlements/pilot.yaml` (bagian ini belum ada di file itu) dan ke `entitlements/local.yaml` (di samping `svc-test`). Ditulis `max_usd: 0`; schema sudah menerima bilangan bulat untuk `Usd`, seperti `max_usd: 500` di file yang sama.

- [ ] **Step 4: Jalankan `make unit`.** Harapan: PASS.

- [ ] **Step 5: Tulis uji integrasi `tests/integration/test_metrics.py`** (spec 5.3; harus lulus sebelum task lain bergantung pada `/metrics`)

```python
def test_metrics_rejects_missing_key(applied):
    r = httpx.get(f"{GATEWAY_URL}/metrics", timeout=30)
    assert r.status_code == 401

def test_metrics_accepts_virtual_key(applied, mock):
    with gateway(issue_key("dev1@local.test")) as c:
        assert chat(c, "company-fast").status_code == 200
        r = c.get("/metrics")
    assert r.status_code == 200
    assert re.search(r"^litellm_\w+", r.text, re.M)

def test_scraper_key_cannot_call_models(applied, mock):
    with gateway(issue_key("prometheus")) as c:
        assert c.get("/metrics").status_code == 200
        assert chat(c, "company-fast", max_tokens=1).status_code != 200
    assert mock.requests() == []

def test_service_metrics_cover_redis_and_postgres(applied, mock):
    with gateway(issue_key("dev1@local.test")) as c:
        chat(c, "company-fast")
        text = c.get("/metrics").text
    assert re.search(r"^litellm_\w*redis\w*", text, re.M | re.I)
    assert re.search(r"^litellm_\w*(postgres|db)\w*", text, re.M | re.I)
```

`GATEWAY_URL` dibaca lewat `os.environ`, seperti di `helpers._env`.

- [ ] **Step 6: Jalankan `make up`, lalu `make test`**

Harapan: seluruh suite PASS, termasuk T01–T10 dengan callback menyala.

**Bila `test_metrics_accepts_virtual_key` atau `test_scraper_key_cannot_call_models` gagal, berhenti dan laporkan ke pemilik repo (spec 5.3).** Jangan menonaktifkan autentikasi dan jangan memakai master key.

Bila hanya `test_service_metrics_cover_redis_and_postgres` yang gagal karena pola nama, sesuaikan regex dengan nama family yang sebenarnya dari Step 7, lalu catat alasannya di pesan commit.

- [ ] **Step 7: Catat nama family metrik**

Ambil keluaran `/metrics` dengan key `dev1` dari container `tools`, lalu catat ke `var/metrics-families.txt` (tidak di-commit) nama family untuk:
- total request dan request gagal
- latency total dan waktu token pertama
- respons 429 atau gagal per deployment
- sisa budget team
- kegagalan Redis dan Postgres

Daftar ini menjadi tabel saran alert di Task 9.

- [ ] **Step 8: Commit** `feat: Prometheus metrics with auth and a zero-budget scraper service account`

---

### Task 5: T10 juga memindai `/metrics`

**Files:**
- Modify: `scripts/t10-scan-logs.sh`, `deploy/tests/test_t10_scan.py`

**Interfaces:**
- Consumes: `/metrics` dari Task 4.
- Produces: baris ringkasan `T10 clean (... sumber: litellm-a litellm-b postgres redis postgres:LiteLLM_SpendLogs litellm-a:/metrics litellm-b:/metrics)`.

- [ ] **Step 1: Tulis uji yang gagal di `deploy/tests/test_t10_scan.py`**
  - Tambahkan ke `STUB_DOCKER` cabang `*" exec -T litellm-"*) cat "$STUB_DIR/metrics-$svc"` sebelum cabang `logs`. Nama service diambil dari argumen setelah `-T`.
  - Fixture menulis `metrics-litellm-a` dan `metrics-litellm-b` berisi `litellm_proxy_total_requests_metric_total 2`.
  - Uji baru `test_sentinel_in_metrics_fails`: `metrics-litellm-b` memuat `VKEY`. Hasilnya exit 1 dan stderr memuat `litellm-b:/metrics`.
  - Uji ringkasan yang sudah ada diperbarui agar mengharapkan dua sumber `/metrics`.

- [ ] **Step 2: Jalankan `make unit`.** Harapan: FAIL.

- [ ] **Step 3: Ubah skrip**

Untuk `litellm-a` dan `litellm-b`, ambil metrik dengan:

```sh
compose exec -T "$svc" python -c "import os,urllib.request as u;print(u.urlopen(u.Request('http://localhost:4000/metrics',headers={'Authorization':'Bearer '+os.environ['LITELLM_MASTER_KEY']})).read().decode())"
```

Master key dibaca dari env container, tidak lewat argv host. Kegagalan mengambil metrik adalah `fail`, bukan "bersih". Hasilnya di-grep dengan pola yang sama.

- [ ] **Step 4: Jalankan `make unit`, lalu `make test`.** Harapan: PASS, dan baris T10 menyebut kedua sumber `/metrics`.

- [ ] **Step 5: Commit** `test: T10 also scans /metrics on both replicas`

---

### Task 6: `make test-failure` dengan T12 dan T13

**Files:**
- Create: `scripts/failure-tests.sh` (executable), `deploy/tests/test_failure_tests_script.py`, `tests/failure/test_t12_redis_down.py`, `tests/failure/test_t13_postgres_down.py`
- Modify: `Makefile`, `deploy/tests/test_makefile.py`

**Interfaces:**
- Produces: `scripts/failure-tests.sh ENV [SCENARIO ...]`. Skenario `t12` dan `t13`; Task 7 menambah `t15`. Default menjalankan semua skenario berurutan. Exit 0 hanya bila semua lulus. Target make `test-failure:` dengan resep `scripts/failure-tests.sh $(ENV) $(ARGS)`.
- Env yang diteruskan ke pytest: `T12_RPM_KEY`, `T12_BUDGET_KEY`, `T13_FRESH_KEY`, `T13_WARM_KEY`. Uji membacanya dengan helper `_env` lokal yang melempar `RuntimeError("jalankan lewat make test-failure")` bila kosong.

- [ ] **Step 1: Tulis uji skrip yang gagal di `deploy/tests/test_failure_tests_script.py`**

Stub `docker` mencatat `calls`, mencetak `sk-stubkey0000` untuk `gatewayctl ... key issue`, dan exit 1 untuk `pytest` bila ada `pytest_fail`.

Uji yang ditulis:
- `test_refuses_vm`: argumen `vm`. Hasilnya exit 1, stderr memuat `ENV=local`, `calls` kosong.
- `test_rejects_unknown_scenario`: argumen `local t99`. Hasilnya exit 1 dan `calls` kosong.
- `test_t12_sequence`: argumen `local t12`. Baris berikut muncul berurutan di `calls` sebagai subsequence (pemanggilan `trap` di akhir boleh menyusul): `apply --confirm`, dua `key issue`, pytest `::test_t12_prepare`, `stop redis`, pytest `::test_t12_redis_down`, `up -d --wait redis`, pytest `::test_t12_recovered`.
- `test_restarts_services_when_a_phase_fails`: `pytest_fail` dengan `local t13`. Hasilnya exit 1, dan `calls` diakhiri `up -d --wait redis postgres litellm-a litellm-b`.
- `test_keys_not_in_argv`: tidak ada baris `calls` yang memuat `sk-stubkey0000`. Key diteruskan sebagai `-e T12_RPM_KEY` dan nilainya lewat environment proses.

Di `deploy/tests/test_makefile.py`: `test_failure_target_calls_script`.

- [ ] **Step 2: Jalankan `make unit`.** Harapan: FAIL.

- [ ] **Step 3: Tulis `scripts/failure-tests.sh`**
  - Guard `ENV_NAME = local`.
  - `trap` untuk `EXIT INT TERM` memanggil `compose up -d --wait redis postgres litellm-a litellm-b`.
  - Sebelum skenario pertama, terapkan entitlements (baris "Terapkan entitlements" di tabel kesepakatan). Di stack baru, user uji belum ada sampai entitlements diterapkan, sehingga `key issue` akan gagal.
  - Fungsi `issue USER LABEL` menangkap stdout `key issue`. Label diberi akhiran `$$` agar unik.
  - Fungsi `phase NODE VAR...` memanggil `compose run --rm -T -e VAR... tools pytest -p no:cacheprovider tests/failure/NODE -v`. `-e VAR` tanpa nilai meneruskan nilai dari environment skrip, sehingga key tidak muncul di argv.
  - Alur T12:
    1. `T12_RPM_KEY=$(issue rate1@local.test t12-rpm)` dan `T12_BUDGET_KEY=$(issue budget1@local.test t12-budget)`.
    2. Fase `prepare`.
    3. `stop redis`, lalu fase `redis_down`.
    4. `up -d --wait redis`, lalu fase `recovered`.
  - Alur T13: sama polanya dengan `fresh` dan `warm` dari `dev2@local.test`.
    1. Fase `prepare`.
    2. `stop postgres`, lalu fase `postgres_down`.
    3. `up -d --wait postgres`, lalu fase `recovered`.

- [ ] **Step 4: Tulis pytest fase T12 (`tests/failure/test_t12_redis_down.py`)**
  - `test_t12_prepare(applied, mock)`: dengan `T12_BUDGET_KEY` dan `max_tokens=MOCK_COMPLETION_TOKENS`, kirim request seperti T02 sampai ada yang bukan 200 (maksimal 30). Assert ada penolakan, jadi budget habis.
  - `test_t12_redis_down(mock)`, tanpa `applied` karena apply butuh Redis sehat:
    - kirim 6 request berurutan dengan `T12_RPM_KEY` ke `litellm-a` dalam satu menit
    - kirim 3 request dengan `T12_BUDGET_KEY`
    - assert `ok_rpm <= 3` (`rpm_limit` rate1) dan tidak ada 200 dari key budget
    - cetak dengan `capsys.disabled()`: `T12 behavior=<rejected bila ok_rpm == 0, selain itu enforced> ok=<ok_rpm> rejected=<6-ok_rpm>`
  - `test_t12_recovered(mock)`: polling tiap 5 detik sampai 120 detik dengan `T12_RPM_KEY`, sampai mendapat 200. Assert dapat 200 dan cetak `T12 recovery seconds=N`.

- [ ] **Step 5: Tulis pytest fase T13 (`tests/failure/test_t13_postgres_down.py`)**
  - `test_t13_prepare(applied, mock)`: `T13_WARM_KEY` mendapat 200 di `litellm-a`. `T13_FRESH_KEY` tidak dipakai.
  - `test_t13_postgres_down(mock)`:
    - `T13_FRESH_KEY` pada request pertama bukan 200
    - `T13_WARM_KEY` dipolling tiap 5 detik sampai 300 detik hingga bukan 200
    - cetak `T13 cached_key_seconds=N` dan assert `N <= 300`
  - `test_t13_recovered(mock)`: polling sampai 120 detik dengan `T13_WARM_KEY` hingga 200, lalu cetak `T13 recovery seconds=N`.

- [ ] **Step 6: Tambahkan target `test-failure` ke `Makefile` dan `.PHONY`.** Jalankan `make unit`. Harapan: PASS.

- [ ] **Step 7: Jalankan `make up`, lalu `make test-failure ARGS='t12 t13'`**

Harapan: semua fase PASS, dan baris `T12 ...` dan `T13 ...` tercetak. Setelah selesai, `make ps` menunjukkan semua service healthy.

Bila T13 melewati 300 detik atau pemulihan melewati 120 detik, jangan ubah ambangnya. Catat keluarannya sebagai temuan Gate 3 dan laporkan.

- [ ] **Step 8: Commit** `test: make test-failure runs T12 (Redis down) and T13 (Postgres down) against the local stack`

---

### Task 7: T15, restore ujung ke ujung

**Files:**
- Create: `tests/failure/test_t15_restore.py`
- Modify: `scripts/failure-tests.sh`, `deploy/tests/test_failure_tests_script.py`

**Interfaces:**
- Consumes: `scripts/backup.sh` (stdout = path) dari Task 2, `scripts/restore.sh` dari Task 3, serta `issue` dan `phase` dari Task 6.
- Produces: skenario `t15`, dengan env `T15_OLD_KEY`, `T15_NEW_KEY`, `T15_BUDGET_KEY`. File state `var/t15-before.json` hanya berisi data non-rahasia: daftar `team_id` dengan spend-nya, alias, spend key lama, dan alias key baru.

- [ ] **Step 1: Tulis uji skrip yang gagal**

`test_t15_sequence` di `deploy/tests/test_failure_tests_script.py`. Stub juga menjawab `backup.sh` dan `restore.sh` dengan file skrip palsu di `scripts/` milik repo uji. Langkah berikut harus muncul berurutan di `calls` sebagai subsequence, setelah `apply --confirm`:
1. `key issue` (old, budget)
2. fase `prepare`
3. `scripts/backup.sh local`
4. `key issue` (new)
5. fase `mutate`
6. `CONFIRM=1 scripts/restore.sh local <path dari backup>`
7. fase `verify`

Jalankan `make unit`. Harapan: FAIL.

- [ ] **Step 2: Tambahkan skenario `t15` ke `scripts/failure-tests.sh`**

Dump yang dibuat T15 dibiarkan di `var/backups/` dan akan terhapus oleh retensi.

- [ ] **Step 3: Tulis pytest fase T15 (`tests/failure/test_t15_restore.py`)**
  - `test_t15_prepare(applied, mock)`:
    - dua chat dengan `T15_OLD_KEY`, lalu `settled_key_spend`
    - habiskan `T15_BUDGET_KEY` seperti T02 (`max_tokens=MOCK_COMPLETION_TOKENS`), lalu `settled_key_spend` untuk key itu, supaya spend-nya sudah di database sebelum backup
    - tulis `var/t15-before.json` berisi `{"teams": {team_id: spend}, "old_key_alias": ..., "old_key_spend": ...}` dari `admin()`
  - `test_t15_mutate(mock)`: chat dengan `T15_NEW_KEY` mendapat 200, lalu `settled_key_spend` sampai spend key baru > 0. Spend baru harus sudah ada di database sebelum restore.
  - `test_t15_verify(mock)`. Urutan baca penting: spend dibaca sebelum ada chat baru.
    - `key_spend(T15_OLD_KEY)` sama dengan `old_key_spend` (`math.isclose`, `abs_tol=1e-9`)
    - spend per team sama dengan `teams`
    - chat `T15_NEW_KEY` mendapat 401
    - chat `T15_OLD_KEY` mendapat 200
    - chat `T15_BUDGET_KEY` dengan `max_tokens=MOCK_COMPLETION_TOKENS` bukan 200, jadi budget tetap ditegakkan setelah `FLUSHALL`
    - cetak `T15 restore ok teams=N`

- [ ] **Step 4: Jalankan `make unit`, lalu `make test-failure ARGS=t15`.** Harapan: PASS dan `make ps` sehat.

- [ ] **Step 5: Jalankan `make test`.** Harapan: PASS, karena state lokal setelah restore tetap memenuhi uji acceptance.

- [ ] **Step 6: Commit** `test: T15 backs up, mutates, restores and verifies keys, spend and budgets`

---

### Task 8: `make loadtest` (T16)

**Files:**
- Create: `tests/load/test_t16_load.py`
- Modify: `entitlements/local.yaml`, `Makefile`, `deploy/tests/test_makefile.py`

**Interfaces:**
- Consumes: `applied`, `mock`, `issue_key`, `settled_key_spend`, dan `model_prices` dari `tests/helpers.py`.
- Produces: target `loadtest:` dengan resep `$(COMPOSE) run --rm -T tools pytest -p no:cacheprovider tests/load -v`, serta baris `T16 concurrency=N requests=M p95_ttft_gateway_s=… p95_ttft_direct_s=… p95_ttft_overhead_s=… errors=E`.

- [ ] **Step 1: Tambahkan team uji ke `entitlements/local.yaml`**

```yaml
  # T16 load test: limits high enough that only gateway capacity is measured.
  qa-load:
    alias: "QA Load (uji)"
    models: [company-coding]
    budget: { max_usd: 10000, duration: 30d }
    rpm_limit: 6000
    members:
      - user_id: load1@local.test
        key: { rpm_limit: 6000, budgets: [{ duration: 30d, max_usd: 1000 }] }
```

- [ ] **Step 2: Tulis uji Makefile yang gagal**

`test_loadtest_target_runs_tests_load`: resepnya memuat `tests/load` dan tidak memuat `tests/acceptance`. Jalankan `make unit`. Harapan: FAIL.

- [ ] **Step 3: Tulis `tests/load/test_t16_load.py`**

Konstanta: `LEVELS = (25, 50)`, `WAVES = 4`, `MAX_OVERHEAD_S = 1.0`.

Fungsi `ttft(client, url, body) -> tuple[bool, float]`:
- streaming lewat `httpx`
- waktu dihitung dari kirim sampai baris `data:` pertama yang memuat `content`
- `ok` bernilai true hanya bila status 200 dan stream berakhir dengan `data: [DONE]`

Untuk setiap level dan setiap gelombang, `ThreadPoolExecutor(max_workers=N)` dengan `threading.Barrier(N)` mengirim N stream bersamaan:
- lewat `gateway(key)` ke model `company-coding`
- lalu gelombang yang sama langsung ke `{MOCK_URL}/v1/chat/completions` dengan model `gpt-5.6-terra`

p95 memakai nearest-rank: `sorted(v)[math.ceil(0.95 * len(v)) - 1]`. Setelah semua level selesai, `settled_key_spend(key, total_requests * cost)`.

Assert per level:
- `errors == 0`, dengan `errors` = jumlah request lewat gateway yang tidak `ok`
- semua request langsung ke mock `ok`; bila tidak, baseline tidak sah dan uji gagal dengan pesan tersendiri
- `p95_gateway - p95_direct <= MAX_OVERHEAD_S` Spend total harus `math.isclose(spend, total_requests * cost, rel_tol=1e-6)`, dengan `cost` dihitung dari harga `company-coding` dan usage bawaan mock, seperti `REQUEST_COST_USD` di T02. Cetak baris T16 per level dengan `capsys.disabled()`.

- [ ] **Step 4: Tambahkan target `loadtest` ke `Makefile` dan `.PHONY`.** Jalankan `make unit`. Harapan: PASS.

- [ ] **Step 5: Jalankan `make apply`, lalu `make loadtest`**

Harapan: PASS dan dua baris T16 tercetak. Angka di laptop hanya untuk pengembangan. Angka resmi diambil di VM (Task 9, checklist Gate 3). Bila gagal, jangan ubah `MAX_OVERHEAD_S`; laporkan sebagai temuan.

- [ ] **Step 6: Commit** `test: make loadtest measures gateway first-token overhead at 25 and 50 streams (T16)`

---

### Task 9: Dokumen Fase 2

**Files:**
- Create: `docs/devops-handoff.md`, `docs/gate3-checklist.md`
- Modify: `docs/operator-guide.md`, `docs/setup-admin.md`, `docs/LITELLM_IMPLEMENTATION_GUIDE.md`, `deploy/tests/test_docs_access.py`

**Interfaces:**
- Consumes: semua target make (Task 2, 3, 6, 8) dan `var/metrics-families.txt` (Task 4 Step 7).

- [ ] **Step 1: Tulis uji dokumen yang gagal**

Tambahkan ke `DOCS` di `deploy/tests/test_docs_access.py`. Daftar `STALE` juga berlaku untuk file baru.

```python
"docs/devops-handoff.md": ["/metrics", "Authorization: Bearer", "var/backups", "/health/liveliness", "26 jam"],
"docs/gate3-checklist.md": ["make test-failure", "make loadtest", "LITELLM_PORT=4100", "15 2 * * *", "T14"],
```

Tambahkan juga `"make backup"` dan `"make restore"` ke entri `docs/operator-guide.md`, serta `"crontab"` ke `docs/setup-admin.md`. Jalankan `make unit`. Harapan: FAIL.

- [ ] **Step 2: Tulis `docs/devops-handoff.md`**

Isinya sesuai spec bagian 3, 5.4, dan 7:
1. Pembagian tugas.
2. Proxy di depan VM, berisi syarat dari spec pilot bagian 10.
3. Monitoring:
   - target `http://<ip-vm>:4000/metrics`, interval 30 detik, header `Authorization: Bearer <key scrape>`
   - `litellm-b` di-scrape setelah portnya dibuka
   - tabel saran alert dengan nama metrik dari `var/metrics-families.txt`
   - cek `/health/liveliness` dari luar
4. Backup: `var/backups/litellm-*.dump`, jadwal 02:15, alert bila file terbaru lebih tua dari 26 jam, dan tujuan salinan harus terbatas aksesnya.
5. Tabel konfirmasi (butir, dikonfirmasi oleh, tanggal).

- [ ] **Step 3: Tulis `docs/gate3-checklist.md`**, dengan pola `docs/pilot-checklist.md`:
  1. **Deploy Fase 2 ke VM:**
     - `git pull`, `make up ENV=vm`
     - `make plan ENV=vm` (harus ada `+ add_service_account prometheus` atau aksi setara), lalu `make apply ENV=vm`
     - `make -s ctl ENV=vm ARGS='key issue --user prometheus --label scrape'`, kirim ke DevOps lewat kanal aman
  2. **Backup:**
     - pasang crontab (baris dari spec 4.2, dengan `PATH`)
     - `make -s backup ENV=vm` manual sekali
     - keesokan harinya cek `var/backups/backup.log`
  3. **T12, T13, T15** (`make test-failure` di stack lokal): salin baris keluarannya.
  4. **T16 di VM** di luar jam kerja:
     - `make init-local` bila belum ada `deploy/env/local.env`
     - operator sendiri mengubah `LITELLM_PORT=4100` di file itu
     - `make up`, `make loadtest`, lalu `make down` (tanpa `-v`)
     - cek manual: jumlah `rpm_limit` team dibandingkan limit tier OpenAI
  5. **T14:** menunggu load balancing DevOps; langkahnya ditulis saat alamat tersedia.
  6. **Konfirmasi DevOps:** rujuk `docs/devops-handoff.md`.
  7. **Tabel hasil** (uji, hasil, tanggal, operator).

- [ ] **Step 4: Perbarui `docs/operator-guide.md` dan `docs/setup-admin.md`**
  - Operator guide:
    - bagian "Backup dan restore": `make backup`, `make restore BACKUP=… CONFIRM=1`, syarat salt key yang sama, runbook spec 4.4
    - di bagian 5: `make test-failure` dan `make loadtest`
  - Setup admin: B9 "Backup harian (crontab)", B10 "Key untuk Prometheus DevOps", dan di Bagian C "Memulihkan dari backup" yang merujuk ke operator guide.

- [ ] **Step 5: Ubah dua baris di `docs/LITELLM_IMPLEMENTATION_GUIDE.md`**
  - Bagian 1: `| State | Managed PostgreSQL + managed Redis 7.0+ |` menjadi `| State | Postgres dan Redis sebagai container di VM, backup harian (spec Fase 2) |`.
  - Fase 2: butir `Managed Postgres (backup harian, point-in-time recovery) dan managed Redis 7.0+` menjadi `Postgres dan Redis sebagai container di VM, backup harian (spec Fase 2)`.
  - Bagian lain tidak diubah.

- [ ] **Step 6: Jalankan `make unit`.** Harapan: PASS.

- [ ] **Step 7: Commit** `docs: DevOps handoff, Gate 3 checklist, backup/restore and failure-test runbooks`

---

### Task 10: Verifikasi menyeluruh dan PR

- [ ] **Step 1:** Jalankan `make unit`, lalu `make test`. Keduanya PASS.
- [ ] **Step 2:** Jalankan `make test-failure`, lalu `make loadtest`, berurutan dan tidak bersamaan dengan `make test`. Keduanya PASS. Salin baris T12, T13, T15, dan T16 untuk deskripsi PR.
- [ ] **Step 3:** `make ps` menunjukkan semua service healthy. `git status` bersih, dan `var/` tidak ikut ter-commit.
- [ ] **Step 4:** Minta izin pemilik repo untuk push, lalu buat PR. Deskripsi PR berisi:
  - ringkasan per task
  - keluaran T12, T13, T15, T16 (laptop)
  - nama metrik yang dipakai
  - langkah di VM yang masih harus dijalankan operator menurut `docs/gate3-checklist.md`
