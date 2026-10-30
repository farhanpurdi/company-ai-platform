# Checklist pilot: deploy VM, smoke, dan Gate 2

Dasar menyalakan stack, perintah `gatewayctl`, dan troubleshooting ada di `docs/operator-guide.md`. Semua perintah dijalankan dari root repo di VM. Host hanya butuh Docker dan `make`. Jangan menjalankan `make down` atau menghapus volume tanpa persetujuan pemilik repo: key, team, dan spend ikut hilang.

## 1. Konfirmasi Gate 1

Nilai sementara (spec bagian 10) berlaku sampai dikonfirmasi. Catat keputusan dan tanggalnya.

| Keputusan | Nilai sementara | Dikonfirmasi (nilai, tanggal, oleh) |
| --- | --- | --- |
| Zona waktu reset budget | UTC | |
| Toleransi overshoot (T03) | 10% dari limit | |
| Target waktu pencabutan key (T05) | 5 menit | |
| Akses jaringan dan TLS | HTTP langsung ke `litellm-a` di `LITELLM_PORT`; TLS dan proxy oleh DevOps (spec bagian 10) | |
| Versi LiteLLM | `v1.106.4` dipin digest (tidak ada tag `-stable` berversi) | |
| Harga Terra/Sol (`model_info`) | Per 1M token, tier Standard, input / input cache / output: Terra $2 / $0.20 / $12, Sol $4 / $0.40 / $20. Harga Sol promo sampai setidaknya 2026-11-21; cek ulang pada tanggal itu (`docs/operator-guide.md`, "Mengubah harga model") | Diverifikasi ke halaman harga OpenAI: |

## 2. Deploy VM

1. `cp deploy/env/vm.env.example deploy/env/vm.env`, isi semua nilai dari secret manager (master key, salt key, password, `OPENAI_API_KEY` milik OpenAI Project khusus gateway), lalu `chmod 600 deploy/env/vm.env`. `LITELLM_SALT_KEY` tidak boleh diganti setelah ada data.
2. Isi `LITELLM_PORT` di `vm.env` (default 4000). Pastikan port itu terbuka dari jaringan kantor di firewall VM dan belum dipakai aplikasi lain (`docs/setup-admin.md` B1). Tidak ada sertifikat: virtual key dan master key lewat jaringan kantor tanpa enkripsi sampai proxy DevOps dipasang (spec bagian 10).
3. `make up ENV=vm`, lalu `make ps ENV=vm`: semua service `healthy`/`running`. Dari laptop di jaringan kantor, `curl -sS http://<ip-vm>:<LITELLM_PORT>/health/liveliness` harus menjawab 200.
4. `make plan ENV=vm` (exit 2 = ada perubahan; tinjau rencananya), lalu `make apply ENV=vm` dengan `OPERATOR` terisi. Di database baru tidak ada aksi destruktif; bila apply meminta `--confirm`, berhenti dan periksa plan. Ulangi `make plan ENV=vm`: harus exit 0.
5. Terbitkan key smoke: `SMOKE_KEY=$(make -s ctl ENV=vm ARGS='key issue --user smoke@perusahaan.com --label smoke')`. Key hanya tampil sekali; jangan ditulis ke file atau chat.

## 3. Smoke otomatis (T06, T07)

1. Snapshot spend sebelum smoke (`SPEND` adalah alias untuk perintah di bawah; keluaran JSON ke stdout, log compose ke stderr):

   ```sh
   SPEND="docker compose -p llm-gateway-vm -f deploy/compose.yaml -f deploy/compose.vm.yaml --env-file deploy/env/vm.env run --rm -T tools python tests/smoke/spend_report.py"
   mkdir -p var && $SPEND 2>/dev/null > var/spend-before.json
   ```

2. `SMOKE_KEY="$SMOKE_KEY" make smoke ENV=vm`. Key diberikan lewat environment, bukan sebagai argumen `make`, agar tidak terlihat di daftar proses (`ps`). Harapan: 4 test PASS (stream >= 5 chunk, token pertama < 30 detik, dan token tiba bertahap; tool call `get_current_time` di `company-coding` dan `company-reasoning`).
3. Catat hasil di bagian 6.

## 4. Manual (T06, T07)

Dengan `docs/opencode.example.json` dan `COMPANY_LLM_KEY` diisi key smoke (budget $2; hentikan bila mendekati batas). `baseURL` diisi `http://<ip-vm>:<LITELLM_PORT>/v1`, tanpa file CA (`docs/setup-admin.md` B7). Pakai hanya dari jaringan kantor, karena key terkirim tanpa enkripsi.

- [ ] **T06:** sesi OpenCode >= 10 menit di `company-coding`, lalu di `company-reasoning`. Token mengalir bertahap, tanpa putus atau timeout.
- [ ] **T07:** tugas agent yang mengedit file (baca file, ubah, jalankan perintah) di kedua alias. Tool call dan hasilnya terproses benar.

## 5. Rekonsiliasi spend (T11)

Harga di `deploy/litellm/config.yaml` harus sudah sama dengan halaman harga OpenAI (bagian 1). Spend yang tercatat sebelum harga diubah memakai harga lama, jadi ambil snapshot `spend-before.json` setelah perubahan harga di-deploy.

1. Setelah smoke dan sesi manual selesai, tunggu beberapa menit agar spend tertulis.
2. Selisih spend: `$SPEND --compare /repo/var/spend-before.json 2>/dev/null`. Keluaran berisi selisih per team dan `total` dalam USD.
3. Bandingkan `total` dengan biaya OpenAI Project di dashboard (pakai OpenAI Project khusus gateway agar tidak tercampur). Dashboard menampilkan biaya per hari dan tidak bisa memisahkan jendela beberapa menit, jadi lakukan uji pada hari yang tidak punya pemakaian gateway lain, atau tambahkan spend gateway di luar jendela uji pada hari itu.
4. Lulus bila selisih < 5%. Catat angkanya di bagian 6.

## 6. Catatan hasil Gate 2

Status per 2026-10-31: 10 dari 11 uji lulus. T11 belum lulus dan menunggu diulang.

| Uji | Hasil | Tanggal | Operator |
| --- | --- | --- | --- |
| T01 akses model (`make test`) | Lulus | 2026-10-30 | Farhan Purdi |
| T02 budget habis (`make test`) | Lulus | 2026-10-30 | Farhan Purdi |
| T03 overshoot (`make test`, baris `T03 spend=... overshoot=...`) | Lulus: `T03 spend=0.0960 overshoot=-4.0% ok=12 rejected=8 upstream=12` | 2026-10-30 | Farhan Purdi |
| T04 rate limit (`make test`) | Lulus | 2026-10-30 | Farhan Purdi |
| T05 waktu pencabutan (`T05 revocation seconds=...`, target <= 300) | Lulus: `T05 revocation seconds=0 statuses={'litellm-a': 401, 'litellm-b': 401}` | 2026-10-30 | Farhan Purdi |
| T06 smoke otomatis + sesi manual | Lulus. Smoke 2/2 PASS (`company-coding`, `company-reasoning`). Sesi OpenCode manual di kedua alias: token mengalir bertahap, tanpa putus atau timeout | 2026-10-30 | Farhan Purdi |
| T07 smoke otomatis + tugas agent | Lulus. Smoke 2/2 PASS (`get_current_time` di kedua alias). Tugas agent `belanja.py` di kedua alias: membaca dan mengedit file, menjalankan perintah, 16 unittest OK | 2026-10-30 | Farhan Purdi |
| T08 retry (`make test`) | Lulus | 2026-10-30 | Farhan Purdi |
| T09 fallback (`make test`) | Lulus | 2026-10-30 | Farhan Purdi |
| T10 kebersihan log (`make test`) | Lulus: `T10 clean (4 nilai, sumber: litellm-a litellm-b postgres redis postgres:LiteLLM_SpendLogs)` | 2026-10-30 | Farhan Purdi |
| T11 spend gateway / OpenAI / selisih | Belum lulus. Percobaan 1, 13:11:23–13:38:16 UTC: gateway $0.4216 di jendela uji ($0.4426 kumulatif hari itu) / OpenAI belum dicatat / selisih belum dihitung. Spend dihitung dengan harga yang sudah usang (Terra $2.50/$15, Sol $5/$30); harga diperbarui di PR #10. Ulangi setelah deploy, pada hari UTC tanpa pemakaian dengan harga lama | 2026-10-30 | Farhan Purdi |

T01-T05 dan T08-T10 diperoleh dari `make test` terhadap stack lokal (mock upstream); salin keluaran `T03`, `T05`, dan `T10` dari sana. Hasil di atas berasal dari commit `5b9a44a`, yang isinya sama dengan `main` di `c1b52a7` (PR #10): unit 341 passed, integration dan acceptance 17 passed. `make test` itu dijalankan lewat Claude Code di laptop operator. T06, T07, dan percobaan 1 T11 dijalankan di VM.

Setelah selesai, blokir key smoke: `make ctl ENV=vm ARGS='key block --user smoke@perusahaan.com'`.
