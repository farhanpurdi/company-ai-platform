# Desain Pilot LiteLLM Gateway (Fase 0–1)

Tanggal: 27 Oktober 2026
Status: Menunggu review
Acuan: `docs/LITELLM_IMPLEMENTATION_GUIDE.md`, `docs/LLM_GATEWAY_ARCHITECTURE.md`

## 1. Tujuan

Membangun repo yang menjalankan pilot LiteLLM gateway sesuai Fase 0–1 panduan implementasi: satu endpoint internal, virtual key per user, budget dan rate limit per user dan team, serta bukti uji T01–T11 untuk Gate 2.

Pengguna repo adalah tim platform/DevOps. Pengguna akhir hanya menerima virtual key dan template OpenCode.

Pilot dinyatakan berhasil bila:

- Stack berjalan di profil lokal (dengan mock upstream) dan profil VM (dengan OpenAI asli) dari definisi layanan yang sama.
- Team, member, dan policy key dikelola dari `entitlements.yaml` melalui `gatewayctl`.
- `make test` lulus untuk unit, integrasi, dan acceptance T01–T05, T08–T10.
- `make smoke` serta checklist manual lulus untuk T06, T07, dan T11 terhadap OpenAI asli.

### Lingkup

- Docker Compose untuk profil lokal dan VM.
- `config.yaml` LiteLLM, konfigurasi Caddy.
- CLI Python `gatewayctl` untuk provisioning deklaratif dan lifecycle key.
- Mock upstream yang meniru OpenAI.
- Suite uji dan skrip smoke.
- Panduan onboarding singkat dan template OpenCode.

### Di luar lingkup

- Fase 2 (Kubernetes/Helm, managed Postgres/Redis, HA produksi) dan uji T12–T16.
- Dashboard Prometheus/Grafana dan alerting.
- Integrasi IdP/SSO/SCIM, portal custom, guardrail/PII masking.
- Pipeline CI. `make test` dirancang agar bisa dipanggil dari CI apa pun yang memiliki Docker.

Struktur tidak boleh menghalangi Fase 2: `gatewayctl` hanya bergantung pada URL LiteLLM dan master key, dan `config.yaml` dipakai ulang apa adanya.

## 2. Keputusan desain

| Topik | Keputusan | Alasan |
| --- | --- | --- |
| Lingkungan pilot | Lokal dulu, lalu VM | Iterasi cepat tanpa biaya OpenAI; VM memakai definisi yang sama |
| Runtime | Semua layanan dan tool berjalan di Docker | Host cukup memiliki Docker dan `make` |
| Provisioning | Deklaratif: `entitlements.yaml` + `gatewayctl plan/apply` | Satu sumber kebenaran, bisa di-review di PR, sekaligus jejak audit |
| Bahasa tool | Python 3.12 | Preferensi tim |
| Pendekatan reconcile | CLI sendiri (bukan Terraform, bukan apply-ulang-semua) | Tidak menyimpan key di state, mendukung dry-run dan pencabutan |
| Pengujian | Dua lapis: otomatis terhadap mock upstream, smoke terhadap OpenAI asli | Skenario kegagalan (429/5xx, fallback) dapat diulang tanpa biaya |
| Reverse proxy | Caddy | TLS internal otomatis di lokal, konfigurasi streaming sederhana. Dapat diganti Nginx tanpa memengaruhi komponen lain |

## 3. Struktur repo

```
company-ai-platform/
├── deploy/
│   ├── compose.yaml             # layanan inti: litellm (2 replika), postgres, redis, caddy
│   ├── compose.local.yaml       # overlay lokal: + mock-upstream, TLS internal Caddy
│   ├── compose.vm.yaml          # overlay VM: sertifikat perusahaan, allowlist VPN
│   ├── litellm/config.yaml
│   ├── caddy/Caddyfile.local
│   ├── caddy/Caddyfile.vm
│   └── env/local.env.example, env/vm.env.example
├── entitlements/
│   ├── local.yaml               # team/user dummy untuk uji
│   └── pilot.yaml               # team/user pilot sebenarnya
├── gatewayctl/                  # paket Python: pyproject.toml, src/gatewayctl/, tests/
├── mock_upstream/               # aplikasi FastAPI
├── tools/Dockerfile             # image berisi gatewayctl, pytest, dan dependensi uji
├── tests/
│   ├── integration/             # gatewayctl terhadap stack lokal
│   ├── acceptance/              # T01–T05, T08–T10 terhadap mock
│   └── smoke/                   # T06, T07, T11 terhadap OpenAI asli
├── docs/
│   ├── LITELLM_IMPLEMENTATION_GUIDE.md
│   ├── LLM_GATEWAY_ARCHITECTURE.md
│   ├── onboarding.md
│   └── opencode.example.json
├── var/                         # audit.log; di-gitignore
├── Makefile
└── .gitignore                   # *.env (kecuali *.env.example), var/
```

## 4. Deploy

### 4.1 Layanan

| Container | Fungsi | Catatan |
| --- | --- | --- |
| `litellm-a`, `litellm-b` | Proxy | Image dipin ke digest (min. v1.93.0-stable). Dua replika juga di lokal agar uji counter dan pemblokiran key mencakup lebih dari satu proses |
| `postgres` | Key, team, spend | `postgres:16`; tidak membuka port ke host |
| `redis` | Counter dan rate limit | `redis:7` dengan password; tidak membuka port ke host |
| `caddy` | Reverse proxy TLS | Load balancing ke kedua replika |
| `mock-upstream` | Peniru OpenAI | Hanya di profil lokal |
| `tools` | `gatewayctl` dan pytest | Dijalankan dengan `docker compose run --rm tools ...` |

Semua replika LiteLLM menunggu Postgres dan Redis sehat. Caddy hanya meneruskan trafik ke replika yang lolos healthcheck `/health/liveliness`.

### 4.2 Pemisahan inference dan admin

Caddy melayani dua hostname:

- `llm.<domain>`: hanya path inference yang di-allowlist (`/v1/chat/completions`, `/v1/models`, `/health/liveliness`). Path lain dibalas 404.
- `llm-admin.<domain>`: Admin UI dan management API. Di VM hanya dari CIDR VPN; di lokal hanya terikat ke `127.0.0.1`.

Untuk streaming: `flush_interval -1` dan timeout baca 600 detik. Access log Caddy tidak mencatat header kredensial.

`tools` berbicara langsung ke `http://litellm-a:4000` melalui jaringan internal compose, sehingga tidak perlu lewat VPN.

### 4.3 Alur

| Langkah | Lokal | VM |
| --- | --- | --- |
| Siapkan secret | `make init-local` membuat secret acak ke `deploy/env/local.env` | Isi `deploy/env/vm.env` dari secret manager, izin file 600 |
| Jalankan stack | `make up` | `make up ENV=vm` |
| Provisioning | `make apply ENV=local` (memakai `entitlements/local.yaml`) | `make plan ENV=vm`, lalu `make apply ENV=vm` (memakai `entitlements/pilot.yaml`) |
| Uji | `make test` | `make smoke ENV=vm` |

`make up` membungkus `docker compose -f deploy/compose.yaml -f deploy/compose.<env>.yaml --env-file deploy/env/<env>.env up -d`.

### 4.4 Aturan di semua profil

- `LITELLM_MODE=PRODUCTION`.
- `allow_requests_on_db_unavailable` tidak diaktifkan (fail-closed).
- Response caching mati.
- `LITELLM_SALT_KEY` tidak pernah diganti setelah ada data.

## 5. Konfigurasi LiteLLM

Tambahan terhadap `config.yaml` di panduan bagian 5.2:

- **`api_base: os.environ/OPENAI_API_BASE`** pada setiap deployment. Lokal mengarah ke `http://mock-upstream:8080/v1`, VM ke `https://api.openai.com/v1`.
- **Harga dipin di `model_info`** (`input_cost_per_token`, `output_cost_per_token`): Terra $2.50/$15 dan Sol $5/$30 per 1M token. Perhitungan spend tidak bergantung pada cost map bawaan, dan langkah reload cost map dihapus dari checklist. Harga diverifikasi ke halaman harga OpenAI sebelum Gate 2.
- **Retry dan fallback:** `num_retries: 2` dengan backoff, `fallbacks: [{"company-reasoning": ["company-coding"]}]`, `request_timeout: 600`.
- **Privasi log:** `turn_off_message_logging: true`, prompt tidak disimpan di spend log, `LITELLM_LOG=INFO`, `json_logs: true`.
- **Redis:** `redis_host`, `redis_port`, `redis_password` (bukan `redis_url`).

## 6. `gatewayctl`

### 6.1 Format `entitlements.yaml`

```yaml
version: 1
teams:
  it-developer:
    alias: "IT / Developer"
    models: [company-fast, company-coding, company-reasoning]
    budget: { max_usd: 500, duration: 30d }
    rpm_limit: 600
    member_defaults:
      max_budget_in_team: 100
      key:
        rpm_limit: 60
        budgets: [{ duration: 24h, max_usd: 10 }, { duration: 30d, max_usd: 100 }]
    members:
      - budi@perusahaan.com
      - { user_id: sari@perusahaan.com, max_budget_in_team: 150 }
service_accounts:
  svc-helpdesk-bot:
    team: it-developer
    models: [company-fast]
    rpm_limit: 120
    budgets: [{ duration: 30d, max_usd: 50 }]
```

Member dapat ditulis sebagai string (memakai `member_defaults`) atau objek yang meng-override sebagian nilai, termasuk `key`. Bila `models` pada key tidak diisi, key mewarisi model team.

### 6.2 Validasi lokal

Dijalankan oleh semua perintah sebelum memanggil API. File ditolak bila:

1. Ada alias yang tidak terdapat di `model_list` pada `deploy/litellm/config.yaml`.
2. Model key atau service account bukan himpunan bagian model team-nya.
3. Team memiliki alias sumber fallback tanpa alias tujuannya (dibaca dari `router_settings.fallbacks`).
4. Satu user terdaftar di lebih dari satu team.
5. Nama service account bentrok dengan `user_id`.

Pesan error menunjuk path di YAML, misalnya `teams.finance.models[2]: alias 'company-x' tidak ada di config.yaml`.

### 6.3 Perintah

| Perintah | Perilaku |
| --- | --- |
| `gatewayctl plan [--json]` | Menampilkan selisih file dengan kondisi LiteLLM. Exit 0: tidak ada perubahan, 2: ada perubahan |
| `gatewayctl apply [--confirm] [--prune]` | Menerapkan selisih. Aksi destruktif (mengeluarkan member, mempersempit model, memblokir key) memerlukan `--confirm`. Penghapusan team memerlukan `--prune` |
| `gatewayctl key issue --user U --label L` | Menerbitkan key untuk user atau service account yang terdaftar, memakai policy dari file. Alias key `<user>-<label>`. Key mentah dicetak sekali ke stdout dan tidak disimpan |
| `gatewayctl key block (--user U \| --alias A)` | Pemblokiran darurat tanpa mengubah file |
| `gatewayctl key list [--user U] [--team T]` | Alias, pemilik, team, status, spend. Tanpa key mentah |

Opsi global: `--file` (default sesuai `ENV`), `--base-url`, master key dari env `LITELLM_MASTER_KEY`.

### 6.4 Semantik reconcile

- **Team** dibuat atau diperbarui (`alias`, `models`, budget, `rpm_limit`) agar sama dengan file.
- **Membership** ditambah atau diperbarui (`max_budget_in_team`). User yang hilang dari file dikeluarkan dari team dan **semua key miliknya diblokir**. Inilah alur offboarding.
- **Key yang sudah ada** milik user terdaftar diperbarui policy-nya (model, RPM, budget) agar sama dengan file. `apply` tidak pernah membuat key.
- **Penandaan:** resource yang dibuat atau diubah oleh `gatewayctl` diberi metadata `managed_by: gatewayctl`. Resource tanpa tanda ini dilaporkan sebagai *unmanaged* dan tidak disentuh.
- **Team yang hilang dari file** hanya ditandai di `plan` dan diproses bila `--prune`: semua key team diblokir, member dikeluarkan, lalu team dihapus.
- **Urutan aksi:** penambahan (team → member → policy key) lalu pengurangan (pemblokiran key → pengeluaran member → penghapusan team). Bila `apply` hanya berisi pengurangan, pemblokiran key berjalan lebih dulu agar akses dicabut secepatnya.

### 6.5 Struktur internal

| Modul | Tanggung jawab | Bergantung pada |
| --- | --- | --- |
| `schema.py` | Model pydantic untuk file, parsing, validasi 6.2 | `config.yaml` (dibaca untuk alias dan fallback) |
| `client.py` | HTTP ke management API LiteLLM; menyamarkan `Authorization` di semua error dan log | `httpx` |
| `state.py` | Mengambil kondisi saat ini (team, member, key) menjadi model yang sama dengan `schema.py` | `client.py` |
| `diff.py` | Fungsi murni: `diff(desired, actual) -> list[Action]`, sudah terurut | — |
| `apply.py` | Menjalankan aksi satu per satu, menulis audit | `client.py` |
| `audit.py` | Menulis JSONL ke `var/audit.log` | — |
| `cli.py` | Perintah Typer | semua di atas |

### 6.6 Audit

Setiap aksi `apply`, `key issue`, dan `key block` menulis satu baris JSONL ke `var/audit.log`: waktu, operator (env `GATEWAYCTL_OPERATOR`, wajib diisi untuk `apply`), git SHA dari file entitlements, aksi, target, nilai sebelum dan sesudah. Key mentah tidak pernah ditulis; key dirujuk lewat alias dan token hash dari LiteLLM.

### 6.7 Penanganan error

| Situasi | Perilaku | Exit |
| --- | --- | --- |
| File tidak valid | Berhenti sebelum memanggil API | 1 |
| LiteLLM tidak dapat dihubungi atau master key ditolak | Berhenti tanpa perubahan | 3 |
| API gagal di tengah `apply` | Berhenti di aksi pertama yang gagal; aksi yang sudah berhasil tercatat di audit; `apply` ulang aman karena idempoten | 1 |
| Aksi destruktif tanpa `--confirm` | Menampilkan rencana, tidak menjalankan apa pun | 4 |

## 7. Mock upstream

Aplikasi FastAPI di jaringan compose, hanya pada profil lokal.

- `POST /v1/chat/completions`: mode streaming dan non-streaming, termasuk respons tool call bila request berisi `tools`. Selalu mengembalikan `usage` dengan jumlah token tetap (dapat diatur) agar biaya per request dapat diprediksi.
- `GET /v1/models`.
- `POST /_mock/scenario`: mengatur perilaku per model untuk N request berikutnya, misalnya `{"model": "gpt-5.6-sol", "mode": "error_429", "count": 3}`. Mode: `ok`, `error_429`, `error_500`, `slow` (dengan `delay_ms`), `fail_before_stream`, `fail_mid_stream`.
- `GET /_mock/requests`: daftar request yang diterima (model, waktu, header dengan nilai kredensial disamarkan menjadi hash).
- `POST /_mock/reset`.

State disimpan di memori, satu replika.

## 8. Pengujian

### 8.1 Lapisan

| Lapisan | Target | Isi | Perintah |
| --- | --- | --- | --- |
| Unit | Tanpa stack | `schema.py`, `diff.py` (uji tabel), exit code CLI dengan `respx` | `make unit` |
| Integrasi | Stack lokal | `apply` dua kali lalu `plan` exit 0; penghapusan user mengeluarkan member dan memblokir key; resource unmanaged tidak berubah; field LiteLLM yang dipakai (`budget_limits`, `max_budget_in_team`, metadata) ada di versi yang dipin | `make test` |
| Acceptance | Stack lokal + mock | T01–T05, T08–T10 | `make test` |
| Smoke | OpenAI asli | T06, T07, T11 dengan key khusus ber-budget $2 | `make smoke` |

Uji integrasi dan acceptance memakai `entitlements/local.yaml`, menerbitkan key sendiri per uji, dan memanggil `/_mock/reset` sebelum setiap uji.

### 8.2 Kriteria acceptance

| ID | Cara uji | Lulus bila |
| --- | --- | --- |
| T01 | Key Finance memanggil `company-reasoning` | Ditolak dengan error akses model; tidak ada request ke mock |
| T02 | Key ber-budget kecil dipakai hingga habis | Request berikutnya ditolak `budget_exceeded` |
| T03 | 20 request paralel mendekati batas, tersebar ke dua replika | Overshoot ≤ toleransi (sementara 10% dari limit, lihat bagian 10) |
| T04 | Request melebihi `rpm_limit` | 429 dari gateway dan jumlah request di mock tidak bertambah |
| T05 | Blokir key aktif, lalu kirim request ke kedua replika | Semua ditolak dalam ≤ target waktu (sementara 5 menit); waktu aktual dicatat |
| T08 | `error_429` count 2, lalu count 5 | Count 2: sukses dengan 3 panggilan upstream. Count 5: error dengan tepat 3 panggilan |
| T09 | Sol `fail_before_stream`, lalu Sol `fail_mid_stream` | Pertama: jawaban dari Terra. Kedua: stream error tanpa request ke Terra |
| T10 | Prompt dan key berisi string penanda | String penanda tidak ditemukan di log semua container, tabel spend log Postgres, dan access log Caddy |

### 8.3 Smoke terhadap OpenAI asli

- **T06:** skrip streaming ke `company-coding` dan `company-reasoning` memeriksa token tiba bertahap; ditambah checklist manual sesi OpenCode minimal 10 menit.
- **T07:** skrip tool calling (satu tool sederhana) di Terra dan Sol; ditambah checklist manual tugas agent OpenCode yang mengedit file.
- **T11:** skrip mencetak spend gateway per team dalam jendela uji; operator membandingkan dengan dashboard usage OpenAI Project dan mencatat selisih (< 5%).

## 9. Dokumentasi pengguna

`docs/onboarding.md` memuat:

- Cara menyimpan key di env `COMPANY_LLM_KEY`.
- `docs/opencode.example.json` (format panduan 5.5), dengan retry client diminimalkan. Format diverifikasi terhadap versi OpenCode yang dipakai.
- Tabel arti error gateway: 401 key tidak valid atau diblokir, error akses model, 429 rate limit atau budget habis, 5xx masalah upstream.

## 10. Keputusan terbuka dengan nilai sementara

Nilai berikut dipakai pilot hingga dikonfirmasi pada Gate 1:

| Keputusan | Nilai sementara |
| --- | --- |
| Zona waktu reset budget | UTC |
| Toleransi overshoot (T03) | 10% dari limit |
| Target waktu pencabutan key (T05) | 5 menit |
| Domain internal | `llm.perusahaan.internal`, `llm-admin.perusahaan.internal` |
| CIDR VPN | Diisi di `vm.env` |
| Versi LiteLLM | v1.93.0-stable terbaru saat implementasi, dipin ke digest. Catatan implementasi: LiteLLM tidak lagi menerbitkan tag `-stable` berversi (tidak ada `v1.93.0-stable`); yang dipin adalah `v1.106.4@sha256:c169fb3a…`, digest yang sama dengan `main-stable` per 2026-10-27 |

## 11. Risiko

| Risiko | Mitigasi |
| --- | --- |
| Field management API (`budget_limits`, `max_budget_in_team`, metadata pada team/member) berbeda di versi yang dipin | Uji integrasi memverifikasi setiap field; versi dipin ke digest |
| Perilaku mock menyimpang dari OpenAI asli | Smoke T06/T07 terhadap OpenAI asli sebelum Gate 2 |
| Pemblokiran key lambat menyebar antar replika karena cache | T05 diuji dengan dua replika dan waktu aktual dicatat |
| `apply` gagal di tengah jalan | Aksi idempoten, berurutan, dan tercatat di audit |
| Retry client berlapis dengan retry gateway | Template OpenCode meminimalkan retry client; didokumentasikan di onboarding |
