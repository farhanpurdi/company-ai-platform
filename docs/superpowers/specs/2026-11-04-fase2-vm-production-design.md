# Desain Fase 2 LiteLLM Gateway: produksi di VM

Tanggal: 4 November 2026
Status: Menunggu review
Acuan: `docs/LITELLM_IMPLEMENTATION_GUIDE.md` (Fase 2, Gate 3), `docs/superpowers/specs/2026-10-27-litellm-pilot-design.md` (spec pilot), `docs/pilot-checklist.md` (Gate 1 dan Gate 2 lulus)

## 1. Tujuan

VM pilot dinaikkan menjadi produksi yang cukup andal untuk 20–50 pengguna. Data key, team, dan spend bisa dipulihkan. Masalah gateway terlihat di monitoring DevOps. Perilaku saat Redis atau Postgres mati diketahui dan teruji.

Prinsip: gateway berjalan dengan Docker di VM dan diakses lewat HTTP di jaringan internal. Infrastruktur di sekitar VM (TLS, load balancing, monitoring, penyimpanan backup di luar VM) adalah ranah DevOps. Repo ini tidak membangun pengganti untuk itu.

Fase 2 dinyatakan selesai di sisi repo bila:

- `make backup` dan `make restore` berjalan, dan backup harian terjadwal di VM.
- `/metrics` tersedia untuk DevOps dengan key khusus yang tidak bisa memanggil model.
- `make test-failure` lulus untuk T12, T13, dan T15 terhadap stack lokal.
- `make loadtest` memenuhi target T16 di VM.
- Runbook, dokumen serah terima DevOps, dan checklist Gate 3 tersedia.

## 2. Keputusan desain

| Topik | Keputusan | Alasan |
| --- | --- | --- |
| Lokasi produksi | VM pilot dinaikkan menjadi produksi | Team, key, dan spend pilot tetap; tidak ada migrasi. Upgrade diuji di stack lokal (mock) sebelum masuk VM |
| Postgres dan Redis | Tetap container di VM, seperti pilot | Tanpa infrastruktur baru. Redis hanya berisi counter dan rate limit, aman bila hilang |
| Backup | `pg_dump` harian ke `var/backups/` di VM; DevOps menyalin folder itu keluar VM | Repo mengurus LiteLLM, DevOps mengurus infrastruktur. Repo tidak menyimpan kredensial tujuan backup |
| Jadwal backup | Cron di host VM memanggil `make backup ENV=vm` | Backup manual dan terjadwal lewat jalur yang sama; gagal terlihat dari exit code dan log |
| Monitoring | LiteLLM membuka `/metrics`; Prometheus/Grafana milik DevOps yang mengambil metrik, menampilkan dashboard, dan mengirim alert | DevOps sudah punya Prometheus/Grafana |
| Perkiraan beban | 20–50 pengguna | Dasar target T16 |
| Uji yang mematikan container | Diatur dari host oleh skrip, hanya untuk stack lokal | Container `tools` tidak diberi akses socket Docker |

## 3. Lingkup

### Dikerjakan di repo

- Backup dan restore Postgres (bagian 4).
- Metrik Prometheus dan key scraper (bagian 5).
- Uji T12, T13, T15, T16, dan perluasan T10 (bagian 6).
- Dokumen: runbook, serah terima DevOps, checklist Gate 3, dan pembaruan dokumen yang ada (bagian 7).

### Ranah DevOps

Dicatat di `docs/devops-handoff.md` (bagian 7), masing-masing dengan kolom konfirmasi:

- Proxy di depan VM: TLS, load balancing ke `litellm-a` dan `litellm-b`, serta syarat lain dari spec pilot bagian 10.
- Prometheus mengambil `/metrics`, dashboard, dan alert.
- Cek `/health/liveliness` dari luar VM, karena LiteLLM tidak bisa memberi alert saat dirinya sendiri mati.
- Menyalin `var/backups/` keluar VM.

### Di luar lingkup

Kubernetes, managed Postgres/Redis, VM kedua, server Prometheus/Grafana di repo, perubahan versi LiteLLM, dan uji T14 sebelum load balancing DevOps tersedia.

## 4. Backup dan restore

### 4.1 `make backup`

Target make memanggil `scripts/backup.sh` di host, dengan pola yang sama seperti `scripts/t10-scan-logs.sh`. Berlaku untuk `ENV=local` dan `ENV=vm`.

1. Buat `var/backups/` dengan izin 700 bila belum ada. Semua file dibuat dengan `umask 077`, sehingga izinnya 600.
2. Jalankan `pg_dump --format=custom -U litellm -d litellm` di dalam container `postgres` lewat `docker compose exec -T`, lalu tulis keluarannya ke file sementara `var/backups/.litellm-<waktu>.dump.partial`. Koneksi lewat socket lokal container, sehingga password tidak muncul di command line host dan port Postgres tetap tertutup. Bila socket lokal ternyata meminta password, password diambil dari env `POSTGRES_PASSWORD` di dalam container, bukan dari host.
3. Periksa dump dengan `pg_restore --list` (dijalankan di container `postgres`, file lewat stdin).
4. Bila lolos, rename menjadi `var/backups/litellm-<YYYYMMDDTHHMMSSZ>.dump` (UTC). Rename hanya terjadi setelah dump lengkap dan terbaca, sehingga file berakhiran `.dump` selalu lengkap.
5. Hapus `litellm-*.dump` yang lebih tua dari `BACKUP_KEEP_DAYS` hari (default 7). Penghapusan hanya terjadi setelah dump baru berhasil, sehingga kegagalan beruntun tidak menghapus backup terakhir yang baik.
6. Cetak satu baris ringkasan ke stderr (nama file, ukuran, durasi). Exit non-zero bila ada langkah yang gagal, dan file `.partial` dihapus.

### 4.2 Jadwal

Cron di VM, dipasang sekali oleh admin dan didokumentasikan di `docs/setup-admin.md`:

```
PATH=/usr/local/bin:/usr/bin:/bin
15 2 * * * cd <repo> && make -s backup ENV=vm >> var/backups/backup.log 2>&1
```

Backup yang gagal terlihat dari `backup.log` dan dari alert DevOps: file `litellm-*.dump` terbaru lebih tua dari 26 jam.

### 4.3 `make restore BACKUP=<file> CONFIRM=1`

Target make memanggil `scripts/restore.sh`. Perintah ini destruktif: isi database diganti dengan isi dump.

1. Tanpa `CONFIRM=1`: cetak file, profil, dan langkah yang akan dijalankan, lalu keluar dengan exit 1 tanpa mengubah apa pun.
2. Periksa file dengan `pg_restore --list` sebelum menghentikan apa pun.
3. Hentikan `litellm-a` dan `litellm-b`.
4. Jalankan `pg_restore --clean --if-exists --no-owner -U litellm -d litellm` di container `postgres`, dengan dump lewat stdin.
5. Kosongkan Redis (`FLUSHALL`), agar counter budget dan rate limit tidak bertentangan dengan spend hasil restore. Uji T15 membuktikan enforcement budget tetap benar setelahnya.
6. Nyalakan kedua replika dan tunggu sampai sehat.

Restore hanya berhasil penuh bila `LITELLM_SALT_KEY` sama dengan saat backup dibuat. Di VM, `make restore` hanya dijalankan atas permintaan pemilik repo (aturan baru di `CLAUDE.md`).

### 4.4 Pemulihan VM rusak

Runbook di `docs/operator-guide.md`:

1. Siapkan VM baru sesuai `docs/setup-admin.md` bagian B.
2. Isi `deploy/env/vm.env` dengan secret yang sama, termasuk `LITELLM_SALT_KEY`.
3. `make up ENV=vm`.
4. Ambil dump terbaru dari penyimpanan DevOps ke `var/backups/`.
5. `make restore ENV=vm BACKUP=var/backups/<file> CONFIRM=1`.
6. `make plan ENV=vm` harus exit 0. Kirim satu request dengan key yang ada.

Kehilangan data maksimal sejak backup terakhir, yaitu sekitar satu hari.

## 5. Metrik

### 5.1 Config

Di `deploy/litellm/config.yaml`, bagian `litellm_settings`:

```yaml
callbacks: ["prometheus"]
service_callback: ["prometheus_system"]
```

- `prometheus` membuka `/metrics`: request, latency, error, 429 dari upstream, token, spend, dan sisa budget per team/key.
- `prometheus_system` menambah metrik per layanan, termasuk kegagalan Redis dan Postgres.
- `require_auth_for_metrics_endpoint` tidak diubah. Bawaannya, `/metrics` wajib memakai key.
- Image yang dipin (`v1.106.4`) tidak mengecek lisensi Enterprise di integrasi Prometheus. Container LiteLLM berjalan dengan satu worker, jadi `PROMETHEUS_MULTIPROC_DIR` tidak diperlukan.

Label metrik memuat nama team, alias key, dan user, dan tersimpan di Prometheus DevOps. Ini diterima karena masih di jaringan internal. Bila perlu, label tertentu bisa dikecualikan lewat config.

### 5.2 Key scraper

Service account di `entitlements/pilot.yaml`:

```yaml
service_accounts:
  prometheus:
    team: it-developer
    models: [company-fast]
    rpm_limit: 10
    budgets: [{ duration: 30d, max_usd: 0 }]
```

- Budget $0 dengan `fail_closed_budget_enforcement` membuat setiap panggilan model ditolak, sehingga key yang bocor tidak bisa menghabiskan uang.
- Key diterbitkan dengan `make -s ctl ENV=vm ARGS='key issue --user prometheus --label scrape'` dan dikirim ke DevOps lewat kanal aman.
- `entitlements/local.yaml` mendapat service account yang sama untuk uji.

### 5.3 Verifikasi di awal implementasi

Dua asumsi berikut berasal dari pembacaan kode image dan belum dijalankan. Keduanya menjadi uji integrasi permanen:

1. Virtual key biasa (bukan master key) mendapat 200 di `/metrics`; request tanpa key mendapat 401.
2. Key `prometheus` (budget $0) mendapat 200 di `/metrics`, ditolak di `/v1/chat/completions`, dan mock tidak menerima request.

Bila salah satunya gagal, implementasi berhenti dan pemilik repo memutuskan langkahnya. Master key tidak diberikan ke DevOps, dan `/metrics` tidak dibuka tanpa autentikasi.

### 5.4 Target scrape

- `http://<ip-vm>:4000/metrics` dengan header `Authorization: Bearer <key>`.
- Selama load balancing belum ada, cukup `litellm-a`, karena semua trafik pengguna masuk ke sana.
- Setelah port `litellm-b` dibuka (spec pilot bagian 10), kedua replika di-scrape terpisah, tidak lewat load balancer.

## 6. Pengujian

### 6.1 `make test-failure`

`scripts/failure-tests.sh` menjalankan T12, T13, dan T15 secara berurutan:

- Skrip di host menghentikan dan menyalakan container. Pytest di container `tools` (berkas di `tests/failure/`) mengirim request dan memeriksa hasil.
- **Menolak berjalan bila `ENV` bukan `local`.** Uji ini mematikan Postgres dan menjalankan restore.
- Setiap skenario mengembalikan stack ke keadaan sehat saat selesai, juga saat gagal (`trap`).
- `tests/failure/` tidak ikut `make test`. Seperti uji acceptance, jangan dijalankan bersamaan dengan `make test`.
- Key mentah tidak ditulis ke file. Bila sebuah key perlu dipakai lintas langkah, skrip menyimpannya di variabel shell dan meneruskannya lewat environment, seperti `SMOKE_KEY`.

### 6.2 Kriteria

| ID | Cara uji | Lulus bila |
| --- | --- | --- |
| T12 | Key dengan `rpm_limit` kecil dan budget hampir habis. Redis dihentikan, lalu kirim request melebihi limit dan budget. Redis dinyalakan lagi | Tidak ada request sukses melebihi `rpm_limit` maupun budget selama Redis mati. Perilaku dicetak (`T12 behavior=<rejected\|enforced> ok=N rejected=M`). Setelah Redis menyala, request kembali sukses dalam 120 detik |
| T13 | Dua key: satu belum pernah dipakai, satu baru saja dipakai. Postgres dihentikan, lalu kirim request dengan keduanya tiap 5 detik. Postgres dinyalakan lagi | Key yang belum dipakai langsung ditolak. Key yang baru dipakai ditolak dalam ≤ 300 detik (target yang sama dengan T05); waktunya dicetak (`T13 cached_key_seconds=...`). Setelah Postgres menyala, request kembali sukses dalam 120 detik |
| T14 | Menunggu load balancing DevOps | Dicatat di checklist Gate 3 sebagai bergantung pada DevOps |
| T15 | Catat keadaan (team, key, spend key uji), `make backup`, terbitkan dan pakai key baru, `make restore CONFIRM=1` | Team dan spend sama dengan sebelum backup. Key lama berfungsi. Key yang terbit setelah backup ditolak. Budget key uji tetap ditegakkan setelah Redis dikosongkan |
| T16 | `make loadtest`: stream bersamaan ke `company-coding` lewat gateway dan langsung ke mock, pada 25 lalu 50 stream bersamaan | Tanpa error. Selisih p95 waktu token pertama (gateway dikurangi langsung ke mock) ≤ 1 detik. Spend tercatat untuk semua request. Hasil dicetak (`T16 concurrency=N p95_ttft_overhead_s=... errors=0`) |
| T16 (manual) | Jumlah `rpm_limit` semua team (saat ini 1.200 RPM) dibandingkan dengan rate limit tier organisasi OpenAI untuk Terra dan Sol | Jumlahnya di bawah limit organisasi, atau ada keputusan tertulis bila tidak |
| T10 (perluasan) | `scripts/t10-scan-logs.sh` juga memindai keluaran `/metrics` | String penanda, key mentah, dan API key OpenAI tidak ada di `/metrics` |

Ketentuan T13 dan T16 tidak dilonggarkan. Hasil yang tidak memenuhi kriteria dicatat sebagai temuan Gate 3, sama seperti aturan T03 dan T09 di `CLAUDE.md`.

### 6.3 Load test

- Skrip di `tests/load/` dijalankan di container `tools` lewat `make loadtest`. Skrip memakai mock upstream yang mengalirkan token bertahap, plus key uji dengan `rpm_limit` dan budget cukup besar di `entitlements/local.yaml`.
- Angka resmi Gate 3 diambil di VM produksi, di luar jam kerja, dengan stack lokal (`ENV=local`, project `llm-gateway-local`) yang `LITELLM_PORT`-nya diset ke 4100 di `deploy/env/local.env`. Stack ini memakai volume sendiri dan tidak menyentuh stack `llm-gateway-vm`. Dengan begitu angkanya mencerminkan hardware VM tanpa biaya OpenAI.
- Di laptop, `make loadtest` hanya untuk pengembangan.

## 7. Dokumentasi

| File | Perubahan |
| --- | --- |
| `docs/devops-handoff.md` (baru) | Daftar kebutuhan dari DevOps (bagian 3) dengan kolom konfirmasi: proxy (TLS, load balancing, timeout ≥ 600 detik tanpa buffering, header key tidak dicatat), target scrape dan cara memakai key, saran alert dengan nama metrik yang diambil dari `/metrics` versi yang dipin (error rate > 5%, lonjakan latency, lonjakan 429 dari OpenAI, kegagalan Redis/Postgres, spend team mendekati batas, `/health/liveliness` gagal, backup terbaru > 26 jam), dan folder `var/backups/` yang perlu disalin |
| `docs/gate3-checklist.md` (baru) | Pola sama dengan `docs/pilot-checklist.md`: deploy perubahan ke VM (config, service account, cron, backup pertama), penerbitan key scrape, tabel hasil T12–T16, cek manual rate limit OpenAI, dan status konfirmasi DevOps |
| `docs/operator-guide.md` | `make backup`, `make restore`, `make test-failure`, `make loadtest`, dan runbook pemulihan VM rusak (4.4) |
| `docs/setup-admin.md` | Pemasangan cron, penerbitan key scrape, dan restore ke VM baru |
| `docs/LITELLM_IMPLEMENTATION_GUIDE.md` | Hanya dua baris: bagian 1 baris "State" dan butir pertama Infrastruktur Fase 2 menjadi "Postgres dan Redis sebagai container di VM, backup harian (spec Fase 2)" |
| `CLAUDE.md` | Spec dan plan Fase 2 masuk daftar sumber kebenaran. Larangan: jangan `make restore` di VM tanpa diminta. Catatan: `make test-failure` hanya untuk stack lokal; T13 dan T16 tidak dilonggarkan |

## 8. Gate 3

Bagian repo (backup/restore, metrik, T12, T13, T15, T16, runbook) bisa selesai lebih dulu. Gate 3 lulus bila semua berikut tercatat di `docs/gate3-checklist.md`:

- T12, T13, T15, T16 lulus, termasuk cek manual rate limit OpenAI.
- DevOps mengonfirmasi load balancing ke kedua replika, dan T14 lulus melalui load balancer itu.
- DevOps mengonfirmasi dashboard dan alert aktif, beserta cek `/health/liveliness` dari luar.
- DevOps mengonfirmasi `var/backups/` tersalin keluar VM.
- Audit administrasi aktif (`var/audit.log`, sudah ada sejak pilot) dan runbook tersedia.

Langkah uji T14 ditulis di checklist saat load balancing tersedia, mengikuti alamat yang diberikan DevOps.

## 9. Risiko

| Risiko | Mitigasi |
| --- | --- |
| Asumsi `/metrics` (key biasa diterima, key budget $0 tetap bisa scrape) salah | Diverifikasi pertama kali sebagai uji integrasi (5.3); bila gagal, berhenti dan tanya pemilik repo |
| Key yang di-cache tetap diterima lama saat Postgres mati | T13 mengukur waktunya; melewati 300 detik menjadi temuan Gate 3 |
| Restore memakai `LITELLM_SALT_KEY` yang berbeda | Runbook dan `make restore` menyebut syarat ini; salt key disimpan terpisah di secret manager |
| Cron gagal tanpa ada yang tahu | `backup.log` dan alert DevOps untuk backup yang lebih tua dari 26 jam |
| Dump berisi data sensitif (hash key, data team, kredensial terenkripsi) | Izin 600, folder 700, `var/` di-gitignore dan ditolak hook; tujuan salinan DevOps harus terbatas aksesnya |
| `make test-failure` atau `make restore` tidak sengaja dijalankan ke VM | `make test-failure` menolak `ENV=vm`; `make restore` wajib `CONFIRM=1`; aturan di `CLAUDE.md` |
| Callback Prometheus menambah beban atau label berkardinalitas tinggi | T16 diukur dengan callback menyala |
| Stack lokal untuk T16 di VM bersaing sumber daya dengan produksi | Dijalankan di luar jam kerja dan singkat; project dan volume terpisah |
| Satu VM menjadi titik gagal tunggal | Diterima untuk 20–50 pengguna; backup harian dan runbook 4.4, kehilangan data maksimal sekitar satu hari |

## 10. File yang berubah

| File | Status |
| --- | --- |
| `Makefile` | Target baru `backup`, `restore`, `test-failure`, `loadtest` |
| `scripts/backup.sh`, `scripts/restore.sh`, `scripts/failure-tests.sh` | Baru |
| `scripts/t10-scan-logs.sh` | Ikut memindai `/metrics` |
| `deploy/litellm/config.yaml` | `callbacks` dan `service_callback` |
| `entitlements/pilot.yaml`, `entitlements/local.yaml` | Service account `prometheus`; key uji load test di `local.yaml` |
| `tests/integration/` | Uji `/metrics` (5.3) |
| `tests/failure/` | Baru: T12, T13, T15 |
| `tests/load/` | Baru: T16 |
| `deploy/tests/` | Uji unit untuk skrip baru dan config (pola uji yang sudah ada) |
| Dokumen | Bagian 7 |
