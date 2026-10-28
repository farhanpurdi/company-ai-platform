# Checklist pilot: deploy VM, smoke, dan Gate 2

Dasar menyalakan stack, perintah `gatewayctl`, dan troubleshooting ada di `docs/operator-guide.md`. Semua perintah dijalankan dari root repo di VM. Host hanya butuh Docker dan `make`. Jangan menjalankan `make down` atau menghapus volume tanpa persetujuan pemilik repo: key, team, dan spend ikut hilang.

## 1. Konfirmasi Gate 1

Nilai sementara (spec bagian 10) berlaku sampai dikonfirmasi. Catat keputusan dan tanggalnya.

| Keputusan | Nilai sementara | Dikonfirmasi (nilai, tanggal, oleh) |
| --- | --- | --- |
| Zona waktu reset budget | UTC | |
| Toleransi overshoot (T03) | 10% dari limit | |
| Target waktu pencabutan key (T05) | 5 menit | |
| Domain internal | `llm.perusahaan.internal`, `llm-admin.perusahaan.internal` | |
| CIDR VPN | diisi di `vm.env` (`VPN_CIDR`) | |
| Versi LiteLLM | `v1.106.4` dipin digest (tidak ada tag `-stable` berversi) | |
| Harga Terra/Sol (`model_info`) | Terra $2.50/$15, Sol $5/$30 per 1M token | Diverifikasi ke halaman harga OpenAI: |

## 2. Deploy VM

1. `cp deploy/env/vm.env.example deploy/env/vm.env`, isi semua nilai dari secret manager (master key, salt key, password, `OPENAI_API_KEY` milik OpenAI Project khusus gateway, `VPN_CIDR`), lalu `chmod 600 deploy/env/vm.env`. `LITELLM_SALT_KEY` tidak boleh diganti setelah ada data.
2. Letakkan `fullchain.pem` dan `privkey.pem` di `deploy/certs/` dan set `TLS_CERT_DIR` ke path absolut direktori itu. Folder ini tidak pernah di-commit. Bila sertifikat berasal dari CA internal yang tidak dikenal container `tools`, taruh CA-nya di `deploy/certs/` dan set `GATEWAY_CA_BUNDLE=/repo/deploy/certs/<ca>.pem` di `vm.env`.
3. `make up ENV=vm`, lalu `make ps ENV=vm`: semua service `healthy`/`running`.
4. `make plan ENV=vm` (exit 2 = ada perubahan; tinjau rencananya), lalu `make apply ENV=vm ARGS=--confirm` dengan `OPERATOR` terisi. Ulangi `make plan ENV=vm`: harus exit 0.
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

Dengan `docs/opencode.example.json` dan `COMPANY_LLM_KEY` diisi key smoke (budget $2; hentikan bila mendekati batas):

- [ ] **T06:** sesi OpenCode >= 10 menit di `company-coding`, lalu di `company-reasoning`. Token mengalir bertahap, tanpa putus atau timeout.
- [ ] **T07:** tugas agent yang mengedit file (baca file, ubah, jalankan perintah) di kedua alias. Tool call dan hasilnya terproses benar.

## 5. Rekonsiliasi spend (T11)

1. Setelah smoke dan sesi manual selesai, tunggu beberapa menit agar spend tertulis.
2. Selisih spend: `$SPEND --compare /repo/var/spend-before.json 2>/dev/null`. Keluaran berisi selisih per team dan `total` dalam USD.
3. Bandingkan `total` dengan dashboard usage OpenAI Project untuk jendela waktu yang sama (pakai OpenAI Project khusus gateway agar tidak tercampur).
4. Lulus bila selisih < 5%. Catat angkanya di bagian 6.

## 6. Catatan hasil Gate 2

| Uji | Hasil | Tanggal | Operator |
| --- | --- | --- | --- |
| T03 overshoot (`make test`, baris `T03 spend=... overshoot=...`) | | | |
| T05 waktu pencabutan (`T05 revocation seconds=...`, target <= 300) | | | |
| T06 smoke otomatis + sesi manual | | | |
| T07 smoke otomatis + tugas agent | | | |
| T11 spend gateway / OpenAI / selisih | | | |

T01-T05 dan T08-T10 diperoleh dari `make test` terhadap stack lokal (mock upstream); salin keluaran `T03` dan `T05` dari sana.

Setelah selesai, blokir key smoke: `make ctl ENV=vm ARGS='key block --user smoke@perusahaan.com'`.
