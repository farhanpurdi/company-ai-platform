# Serah terima ke DevOps: gateway LiteLLM di VM

Dokumen ini berisi apa yang disediakan repo dan apa yang diminta dari DevOps untuk Fase 2 (spec `docs/superpowers/specs/2026-11-04-fase2-vm-production-design.md`). Gateway berjalan dengan Docker di satu VM dan diakses lewat HTTP di jaringan internal. TLS, load balancing, monitoring, dan penyimpanan backup di luar VM adalah ranah DevOps; repo ini tidak membangun pengganti untuk itu.

## 1. Pembagian tugas

| Hal | Repo / tim gateway | DevOps |
| --- | --- | --- |
| LiteLLM, Postgres, Redis di VM | Mengurus config, versi yang dipin, upgrade | Tidak ada |
| `/metrics` | Membuka endpoint dan menerbitkan key scrape | Prometheus mengambil metrik, dashboard, alert |
| Backup Postgres | `make backup` harian lewat cron di VM, hasilnya di `var/backups/` | Menyalin `var/backups/` keluar VM |
| Proxy di depan VM | Mendaftar syaratnya (bagian 2) | TLS, load balancing, timeout, log |
| Cek hidup dari luar | Menyediakan `/health/liveliness` | Memantau dari luar VM, karena gateway tidak bisa memberi alert saat dirinya sendiri mati |

## 2. Proxy di depan VM

Syarat dari spec pilot bagian 10. Selama proxy belum ada, virtual key dan master key lewat jaringan kantor tanpa enkripsi.

- TLS, sehingga key tidak lagi lewat jaringan tanpa enkripsi.
- Allowlist path pengguna: `/v1/chat/completions`, `/v1/models`, dan `/health/liveliness`. Path lain ditolak. `/metrics` tidak perlu dibuka ke pengguna; Prometheus mengambilnya langsung dari jaringan internal (bagian 3).
- Management API dan Admin UI hanya dari jaringan yang dipercaya.
- Load balancing ke `litellm-a` dan `litellm-b`. Saat ini hanya `litellm-a` yang membuka port ke host; port `litellm-b` dibuka lewat perubahan di repo setelah DevOps siap.
- Timeout baca minimal 600 detik tanpa buffering, agar jawaban streaming yang panjang tidak terputus.
- Header yang membawa key (`Authorization`) tidak dicatat di access log proxy.

## 3. Monitoring

### Target scrape

| Hal | Nilai |
| --- | --- |
| URL | `http://<ip-vm>:4000/metrics/` (pakai garis miring di akhir; `/metrics` dijawab LiteLLM dengan redirect 307 ke alamat itu) |
| Interval | 30 detik |
| Autentikasi | Header `Authorization: Bearer <key scrape>` |
| Replika | Selama load balancing belum ada, cukup `litellm-a`: semua trafik pengguna masuk ke sana. Setelah port `litellm-b` dibuka, scrape kedua replika terpisah, tidak lewat load balancer |

Contoh `scrape_config` Prometheus:

```yaml
scrape_configs:
  - job_name: litellm
    scrape_interval: 30s
    metrics_path: /metrics/
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/litellm-scrape-key
    static_configs:
      - targets: ["<ip-vm>:4000"]
```

### Key scrape

- Key milik service account `prometheus`, diterbitkan oleh tim gateway dengan `make -s ctl ENV=vm ARGS='key issue --user prometheus --label scrape'` dan dikirim lewat kanal aman. Key hanya tampil sekali.
- LiteLLM versi yang dipin hanya mengizinkan admin membaca `/metrics`; key virtual biasa dijawab 401. Karena itu `prometheus` berperan **admin read-only** (`proxy_admin_viewer`): tidak bisa memanggil model (inferensi ditolak, budget $0 ikut memblokir) dan tidak bisa menulis atau mengubah apa pun.
- Perhatian: admin read-only boleh membaca endpoint admin lain lewat GET (daftar key dan team beserta spend, bukan isi key). Simpan key di secret store Prometheus, jangan dibagikan ke pengguna lain, dan jangan membuka port gateway ke jaringan yang tidak dipercaya. Key bocor: kabari tim gateway untuk memblokir dan menerbitkan ulang.
- Master key tidak pernah diberikan ke DevOps. Autentikasi `/metrics` tidak dimatikan.
- Label metrik memuat nama team, alias key, dan user. Isi percakapan dan key mentah tidak ada di `/metrics` (uji T10 memindainya).

### Saran alert

Nama metrik diambil dari `/metrics` versi LiteLLM yang dipin (`v1.106.4`). Histogram dipakai dengan akhiran `_bucket`.

| Kondisi | Metrik | Saran |
| --- | --- | --- |
| Error rate | `litellm_proxy_failed_requests_metric_total` dibagi `litellm_proxy_total_requests_metric_total` | Lebih dari 5% selama 5 menit |
| Latency | `litellm_request_total_latency_metric` (histogram) | p95 naik tajam dibanding biasanya |
| Waktu token pertama | `litellm_llm_api_time_to_first_token_metric` (histogram) | p95 melewati batas yang disepakati |
| 429 dan kegagalan dari OpenAI | `litellm_deployment_failure_responses_total`, `litellm_deployment_state` | Lonjakan, atau state deployment tidak sehat |
| Redis bermasalah | `litellm_redis_failed_requests_total`, `litellm_redis_circuit_breaker_state` | Naik, atau circuit breaker terbuka |
| Postgres bermasalah | `litellm_postgres_failed_requests_total` | Naik |
| Spend team mendekati batas | `litellm_remaining_team_budget_metric` | Sisa budget di bawah 10% |
| Gateway mati | `GET /health/liveliness` dari luar VM | Bukan 200 selama 2 menit |
| Backup tidak berjalan | Umur file `var/backups/litellm-*.dump` terbaru | Lebih tua dari 26 jam |

## 4. Backup

- Cron di VM menjalankan `make backup ENV=vm` setiap hari pukul 02:15. Hasilnya `var/backups/litellm-<YYYYMMDDTHHMMSSZ>.dump` (UTC, izin 600; folder izin 700). Retensi di VM 7 hari.
- DevOps menyalin `var/backups/` keluar VM secara berkala dan memberi alert bila file terbaru lebih tua dari 26 jam. Cron mencatat hasilnya di `var/backups/backup.log`.
- Dump berisi hash key, data team, spend, dan kredensial terenkripsi. Tujuan salinan harus terbatas aksesnya.
- Restore hanya berhasil bila `LITELLM_SALT_KEY` sama dengan saat backup dibuat. Simpan salt key di secret manager, terpisah dari dump.
- Restore dijalankan tim gateway (`docs/operator-guide.md`, "Backup dan restore"). Kehilangan data maksimal sejak backup terakhir, sekitar satu hari.

## 5. Konfirmasi

Isi saat DevOps sudah menyelesaikan butir terkait.

| Butir | Dikonfirmasi oleh | Tanggal |
| --- | --- | --- |
| TLS di depan VM | | |
| Allowlist path pengguna dan pembatasan management API/Admin UI | | |
| Load balancing ke `litellm-a` dan `litellm-b`, timeout baca ≥ 600 detik tanpa buffering | | |
| Header `Authorization` tidak dicatat di access log proxy | | |
| Prometheus mengambil `/metrics/` dengan key scrape | | |
| Dashboard dan alert (bagian 3) aktif | | |
| Cek `/health/liveliness` dari luar VM aktif | | |
| `var/backups/` tersalin keluar VM, tujuan salinan terbatas aksesnya, alert umur backup aktif | | |
