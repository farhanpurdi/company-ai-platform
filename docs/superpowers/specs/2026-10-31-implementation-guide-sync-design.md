# Sinkronisasi LITELLM_IMPLEMENTATION_GUIDE.md: keputusan pilot, tata kelola harga, dan provider kedua

Tanggal: 31 Oktober 2026
Status: Disetujui per bagian lewat diskusi; menunggu review spec tertulis
Dokumen yang diubah: `docs/LITELLM_IMPLEMENTATION_GUIDE.md` (selanjutnya "guide")
Acuan: `docs/LLM_GATEWAY_ARCHITECTURE.md`, `docs/superpowers/specs/2026-10-27-litellm-pilot-design.md` (spec pilot)

## 1. Latar belakang

Guide ditulis 27 Oktober 2026 sebelum pilot dibangun. Sejak itu beberapa keputusan mengubah cara gateway bekerja, dan sebagian isi guide kini bertentangan dengan repo:

- §5.2 dan Fase 1 menyuruh "reload model cost map". Sejak PR #10 harga dipin di `deploy/litellm/config.yaml` dan LiteLLM tidak lagi mengunduh cost map (`LITELLM_LOCAL_MODEL_COST_MAP=True`).
- §5.2 tidak memuat harga yang dipin, `fail_closed_budget_enforcement`, `api_base`, dan `request_timeout`.
- §5.3, Fase 0, dan Fase 1 menggambarkan satu container di belakang reverse proxy HTTPS dengan Admin UI lewat VPN. Pilot berjalan dengan dua replika dan HTTP langsung ke `litellm-a`; TLS dan proxy diurus DevOps (spec pilot §10).
- §5.4 serta runbook 8.1 dan 8.2 memakai `curl` manual ke management API, sedangkan repo memakai `entitlements/*.yaml` dengan `make plan`/`make apply` dan `gatewayctl`.
- §5.5 berbeda dari `docs/opencode.example.json` (`baseURL` HTTPS, tanpa timeout).
- §9 belum memuat risiko perubahan harga provider. Sebagian §10 sudah terjawab.

Diskusi harga (30 Oktober 2026) juga menghasilkan rencana kerja yang belum tercatat: cek perubahan harga berkala, rekonsiliasi rutin, batas belanja di provider, dan arah multi-provider.

## 2. Tujuan dan kriteria sukses

Tujuan: guide kembali menjadi acuan pengerjaan yang benar, tanpa membuka ulang gate rilis awal.

Kriteria sukses:

1. Guide tidak lagi berisi instruksi yang bertentangan dengan repo atau keputusan yang sudah diambil, termasuk "reload cost map" dan `curl` manual untuk team, member, atau budget.
2. Salinan konfigurasi di guide sama persis dengan file repo, dan `make unit` gagal bila tidak sama.
3. Rencana tata kelola harga (Fase 0–3) dan Fase 4 tertulis sebagai item checklist yang bisa dicentang.

## 3. Keputusan (pemilik repo, 31 Oktober 2026)

| Keputusan | Nilai |
| --- | --- |
| Lingkup | Sinkronisasi dengan repo, rencana tata kelola harga, dan arah multi-provider |
| Posisi multi-provider | Fase 4 setelah go-live. Rilis awal tetap OpenAI saja |
| Provider kedua | Belum ditentukan. Fase 4 ditulis generik; pemilihan provider menjadi syarat masuk |
| Rekonsiliasi spend | Manual bulanan di Fase 3; otomatis lewat API biaya provider di Fase 4 |
| Salinan konfigurasi di guide | Diperbarui agar sama dengan repo, dijaga tes |

Asumsi yang tidak dikoreksi pemilik repo:

- Hanya guide yang diubah secara substansial. `LLM_GATEWAY_ARCHITECTURE.md` tidak diubah: prinsipnya tidak bertentangan dan sudah meminta rekonsiliasi biaya gateway dengan laporan provider (§11).
- Bagian target produksi (Kubernetes, ingress TLS, Admin UI lewat VPN) tetap sebagai target. Perbedaan di pilot dicatat, tidak dihapus.
- Tidak ada perubahan kode gateway, config, compose, atau entitlements.
- Kriteria gate G1–G3 dan Go-live tidak diubah. Item baru masuk ke checklist fase.

## 4. Rancangan

### 4.1 Sinkronisasi dengan repo dan keputusan

| Bagian guide | Perubahan |
| --- | --- |
| Header | Tambah "Diperbarui: 31 Oktober 2026" dan rujukan ke spec pilot untuk keputusan pilot |
| §1 Keputusan terkunci | Tambah baris **Harga** (dipin di `config.yaml`, cost map tidak diunduh) dan **Budget** (`fail_closed_budget_enforcement`). Baris Deploy: pilot dua replika (`litellm-a`, `litellm-b`) di satu VM, HTTP langsung; TLS dan proxy oleh DevOps sebelum dipakai luas. Daftar "di luar lingkup rilis awal" diberi rujukan ke Fase 4 |
| §2 Arsitektur | Diagram tetap target produksi. Tambah catatan kondisi pilot (spec pilot §10) |
| §5.1 Env | Tambah `LITELLM_LOCAL_MODEL_COST_MAP`, `OPENAI_API_BASE`, `LITELLM_PORT`, `LITELLM_LOG`, `JSON_LOGS` |
| §5.2 `config.yaml` | Salinan utuh `deploy/litellm/config.yaml`. Kalimat "reload model cost map" diganti rujukan ke prosedur "Mengubah harga model" di `docs/operator-guide.md` |
| §5.3 Compose | Salinan utuh `deploy/compose.yaml` dan `deploy/compose.vm.yaml`. Paragraf reverse proxy menjadi syarat untuk proxy DevOps (TLS, allowlist path, tanpa buffering, timeout baca minimal 600 detik) |
| §5.4 Provisioning | `curl` diganti alur repo: contoh `entitlements/pilot.yaml`, `make plan`/`make apply ENV=vm`, `make ctl` untuk `key issue` dan `key block` |
| §5.5 OpenCode | Salinan utuh `docs/opencode.example.json` |
| §6 Fase 0–1 | Centang item yang selesai, hanya bila ada bukti di repo (spec pilot, `docs/pilot-checklist.md`, PR). Tulis ulang item yang keputusannya berubah (TLS, VPN, reload cost map). Catat status Gate 2: 10 dari 11 uji lulus, T11 menunggu diulang (rujuk `docs/pilot-checklist.md` bagian 6) |
| §7 T11 | Langkah mengikuti `docs/pilot-checklist.md` bagian 5: snapshot spend, hari UTC tanpa pemakaian dengan harga lama, harga di config sesuai halaman provider |
| §8 Runbook | 8.1 dan 8.2 memakai alur entitlements. Tambah 8.7 "Perubahan harga" (bagian 4.2) |
| §10 Pertanyaan terbuka | Tandai yang sudah terjawab beserta nilainya (nilai sementara Gate 1 dari spec pilot §10). Tambah pertanyaan provider kedua (bagian 4.3) |

### 4.2 Tata kelola harga

Prinsip, ditambahkan sebagai §3.1 "Tata kelola harga":

- Harga per token setiap deployment (input, input cache, output) dipin di `config.yaml` dan hanya berubah lewat PR. Harga di config tidak boleh di bawah harga provider. Untuk harga promo, tanggal berakhirnya dicatat.
- Prioritas mengikuti arah perubahan: harga naik wajib diterapkan sebelum tanggal berlaku (bila terlambat, budget bocor sebesar selisihnya); harga turun tidak mendesak.
- Gateway adalah satu-satunya tempat batas per team, untuk semua provider. Batas belanja di provider berfungsi sebagai sekring: kira-kira jumlah budget bulanan semua team yang memakai provider itu ditambah 10–20%. Bila provider hanya mengirim alert tanpa memblokir, hal itu dicatat.

Item rencana:

| Fase | Item | Status awal |
| --- | --- | --- |
| Fase 0 | Item "budget dan alert di level OpenAI Project" diperjelas dengan rumus sekring | Belum |
| Fase 1 | Harga dipin beserta harga cache; cost map dari image (PR #10) | Selesai |
| Fase 1 | Verifikasi harga dicatat di kolom Gate 1 `docs/pilot-checklist.md` | Belum |
| Fase 2 | Cek ulang harga Sol pada 21 November 2026 (akhir promo) | Belum |
| Fase 3 | Rekonsiliasi bulanan manual: spend gateway dibanding tagihan provider; selisih > 5% berarti harga ditinjau; hasil dicatat | Belum |
| Fase 3 | Cek perubahan harga otomatis: job terjadwal tanpa secret (misalnya GitHub Actions) membandingkan harga di config dengan cost map LiteLLM terbaru, dan membuat issue pengingat bila berbeda. Job tidak mengubah config | Belum |
| Fase 3 | Item jadwal "review mapping alias tiap bulan" ditambah "review harga bersama rekonsiliasi" | Belum |

Runbook 8.7 "Perubahan harga": kebijakan arah perubahan, langkah PR, `--force-recreate` kedua replika, verifikasi, rujukan ke `docs/operator-guide.md`.

Risiko di §9:

- Baris baru "Harga provider berubah atau promo berakhir". Dampak: spend tidak cocok dengan tagihan; bila harga naik, budget bocor. Mitigasi: harga dipin dan direview, rekonsiliasi bulanan, cek perubahan harga otomatis, sekring di provider.
- Mitigasi baris "Budget overshoot pada request paralel" dilengkapi `fail_closed_budget_enforcement` dan hasil T03 (overshoot -4%).

### 4.3 Fase 4: otomatisasi rekonsiliasi dan provider kedua

Fase baru di §6 setelah Fase 3, tanpa jumlah minggu: durasi ditetapkan setelah provider dipilih. Dua jalur:

**4a. Otomatisasi rekonsiliasi** (mulai setelah go-live):

- Putuskan penyimpanan kunci admin provider (misalnya OpenAI Admin key): secret manager, siapa yang punya akses, jadwal rotasi.
- Job terjadwal per provider membandingkan spend gateway dengan API biaya provider dan mengirim alert bila selisih > 5%. Rekonsiliasi manual tetap menjadi cadangan.

**4b. Provider kedua** (generik):

Syarat masuk:

- Go-live selesai dan rekonsiliasi bulanan berjalan minimal satu bulan.
- Provider dipilih dengan kriteria tertulis: kelas data dan region (arsitektur §3.1, §12), harga terbuka termasuk harga cache, API atau laporan biaya, fitur batas belanja (blokir atau hanya alert), kompatibilitas OpenCode (streaming, tool calling), rate limit, dan akun atas nama perusahaan.

Checklist:

- Akun atau project khusus gateway di provider; credential hanya di secret manager.
- Sekring batas belanja di provider (bagian 4.2).
- Deployment baru di `config.yaml` dengan ketiga harga dipin; tes `make unit` memeriksa setiap entri `model_list`. Tarif konteks panjang ikut dipin bila provider punya tier dan cost map berbeda.
- Keputusan mapping: alias baru atau deployment tambahan di alias yang sudah ada. Fallback lintas provider hanya antar deployment dengan kelas data dan region yang sama (arsitektur §8, §9).
- Izin di `entitlements/*.yaml`: team mana yang boleh memakai alias baru.
- Budget team tetap satu angka lintas provider di gateway.

Uji, diulang untuk provider baru dengan ID yang sama: T01, T06, T07, T09 (bila ada fallback), T10, dan T11 (spend alias baru dibanding tagihan provider, selisih < 5%).

Gate 4: uji per provider di atas lulus, sekring provider terpasang, rekonsiliasi berjalan (otomatis, atau manual yang tercatat), dan runbook 8.3 diperbarui.

Penyesuaian lain:

- Runbook 8.3 (OpenAI down): catatan bahwa setelah Fase 4, fallback lintas provider dapat dipakai bila diizinkan.
- Risiko "Satu provider (OpenAI)": mitigasi merujuk ke Fase 4.
- §10: tambah "Provider kedua apa, dan berdasarkan kriteria apa?".

### 4.4 Menjaga salinan tetap sinkron

Setiap salinan utuh di guide diawali penanda komentar HTML, langsung diikuti blok kode:

````markdown
<!-- salinan: deploy/litellm/config.yaml -->
```yaml
...isi persis file...
```
````

Salinan utuh: `deploy/litellm/config.yaml`, `deploy/compose.yaml`, `deploy/compose.vm.yaml`, dan `docs/opencode.example.json`.

Tes baru `deploy/tests/test_doc_copies.py`, ikut `make unit`:

1. Untuk setiap penanda `<!-- salinan: <path> -->` di `docs/*.md`, isi blok kode berikutnya sama persis dengan file `<path>` (path relatif terhadap root repo). Pesan gagal menyebut dokumen dan file.
2. Guide memuat penanda untuk keempat file di atas, sehingga menghapus penanda tidak membuat tes lolos diam-diam.

Contoh `entitlements/pilot.yaml` di §5.4 tidak dijaga tes, karena file itu berubah setiap anggota ditambah. Di guide ditandai sebagai contoh dengan rujukan ke file aslinya.

Akibatnya, perubahan `config.yaml` atau compose membuat `make unit` (dan pre-commit) gagal sampai salinan di guide diperbarui. `docs/operator-guide.md`, langkah 2 "Mengubah harga model", menyebut hal ini.

## 5. File yang berubah

| File | Perubahan |
| --- | --- |
| `docs/superpowers/specs/2026-10-31-implementation-guide-sync-design.md` | Spec ini |
| `docs/LITELLM_IMPLEMENTATION_GUIDE.md` | Bagian 4.1–4.4 |
| `deploy/tests/test_doc_copies.py` | Tes salinan (bagian 4.4) |
| `docs/operator-guide.md` | Satu kalimat di langkah 2 "Mengubah harga model" |

## 6. Verifikasi

- `make unit` lulus, termasuk tes salinan. Tes salinan dibuktikan gagal lebih dulu: sebelum guide diperbarui (penanda belum ada) dan saat satu baris salinan sengaja dibuat berbeda.
- `make test` tidak diperlukan karena tidak ada perubahan gateway, tetapi `deploy/tests/test_docs_access.py` tetap lulus (tidak ada instruksi Caddy/TLS lama).
- Pencarian di guide tidak menemukan "reload" cost map, `curl` ke `/team/new`, `/team/member_add`, `/key/generate`, atau `/key/block`, maupun harga lama ($2.50/$15, $5/$30).
