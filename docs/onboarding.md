# Onboarding pengguna: Company LLM Gateway

Dokumen ini untuk pengguna akhir (developer) yang menerima virtual key dari tim platform. Anda hanya butuh key dan template OpenCode.

## 1. Simpan key

Key diberikan sekali lewat kanal aman. Simpan sebagai environment variable `COMPANY_LLM_KEY`; jangan menulisnya di file konfigurasi, repo, atau chat.

```sh
# ~/.zshrc atau ~/.bashrc
export COMPANY_LLM_KEY='sk-...'
```

Buka terminal baru agar variabel terbaca. Key bersifat pribadi: jangan dibagikan. Bila key bocor atau hilang, minta tim platform memblokirnya dan menerbitkan yang baru.

## 2. Pasang template OpenCode

Salin `docs/opencode.example.json` ke `opencode.json` (di root proyek) atau ke `~/.config/opencode/opencode.json` (untuk semua proyek). Template memakai `{env:COMPANY_LLM_KEY}` sehingga key tidak tertulis di file.

Selama pilot, gateway bisa diakses lewat IP sebelum domain siap. Bila tim platform memberi alamat IP dan file CA:

- ganti `baseURL` di template menjadi alamat dari tim platform, misalnya `https://10.0.0.5/v1`;
- simpan file CA, misalnya di `~/llm-gateway-ca.crt`, lalu tambahkan `export NODE_EXTRA_CA_CERTS="$HOME/llm-gateway-ca.crt"` di `~/.zshrc` atau `~/.bashrc`.

Lalu pilih model:

| Model di OpenCode | Alias gateway | Kapan dipakai |
| --- | --- | --- |
| Company Coding (Terra) | `company-coding` | Coding harian dan agent |
| Company Reasoning (Sol) | `company-reasoning` | Masalah sulit, analisis kompleks, agent panjang. Hanya untuk team yang diizinkan |

Alias yang tidak diizinkan untuk team Anda akan ditolak gateway (lihat tabel error di bawah).

## 3. Retry di sisi client

Gateway sudah melakukan retry sendiri (maksimal 2 kali dengan backoff) ke OpenAI, dan untuk `company-reasoning` pindah ke `company-coding` bila gagal sebelum jawaban mulai dikirim.

Hasil pengecekan dokumentasi OpenCode (27 Oktober 2026): opsi provider yang terdokumentasi hanya `timeout`, `headerTimeout`, `chunkTimeout`, dan `setCacheKey`. **Tidak ada pengaturan untuk mematikan atau meminimalkan retry client** di konfigurasi provider; OpenCode melakukan retry sesi sendiri (backoff jitter, hingga 10 kali untuk 429 dan hormat pada header `Retry-After`; maksimal 3 kali untuk timeout). Karena itu:

- Template hanya menaikkan `timeout` dan `headerTimeout` menjadi 600 detik, sama dengan `request_timeout` gateway, agar client tidak memutus request panjang lebih dulu lalu mengulangnya (yang bisa menggandakan biaya).
- Satu aksi pengguna bisa berujung beberapa request ke gateway bila terjadi error. Retry client dan retry gateway berlapis; tim platform memantau efeknya selama pilot (uji T08).
- Verifikasi ulang perilaku ini pada versi OpenCode yang dipakai tim; bila versi baru menyediakan opsi retry, set ke minimum dan perbarui template.

## 4. Arti error dari gateway

| Gejala | Artinya | Yang dilakukan |
| --- | --- | --- |
| 401, key tidak valid atau diblokir | Key salah ketik atau sudah diblokir (misalnya setelah offboarding atau key bocor) | Periksa `COMPANY_LLM_KEY`; bila benar, hubungi tim platform |
| 401/403, pesan akses model (menyebut nama alias) | Team atau key Anda tidak diizinkan memakai alias itu | Pakai alias lain; minta persetujuan tim platform bila butuh akses |
| 429, rate limit | Request per menit melebihi batas key atau team | Tunggu sebentar lalu ulangi; kurangi permintaan paralel |
| 422 dengan tipe error `budget_exceeded` (LiteLLM v1.106.4; terverifikasi di uji T02) | Budget harian/bulanan key atau team habis | Tunggu reset jendela budget (UTC) atau minta tim platform menaikkan budget |
| 5xx | Masalah di gateway atau di OpenAI | Ulangi beberapa saat lagi; bila berlanjut, laporkan ke tim platform beserta waktu kejadian |

Jangan menempelkan key atau isi prompt rahasia saat melapor; waktu kejadian dan nama alias sudah cukup.
