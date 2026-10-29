# Panduan operator: menyalakan dan memakai gateway

Dokumen ini untuk tim platform yang menjalankan gateway. Pengguna akhir cukup membaca `docs/onboarding.md`. Langkah deploy VM dan uji Gate 2 (T06, T07, T11) ada di `docs/pilot-checklist.md`; dokumen ini menjelaskan dasar yang dipakai checklist itu.

## 1. Gambaran singkat

```
client (OpenCode/curl)
  │ HTTP
  ▼
litellm-a (port LITELLM_PORT; litellm-b hanya di jaringan Docker) ──► OpenAI (VM) atau mock-upstream (lokal)
  │
  ├── Postgres: key, team, user, spend
  └── Redis: counter budget dan rate limit lintas replika
```

Tidak ada reverse proxy dan TLS di repo ini. Pengguna dan admin terhubung langsung ke `litellm-a`. `litellm-b` adalah replika kedua yang memakai Postgres dan Redis yang sama, tetapi tidak membuka port ke host sampai proxy DevOps dipasang (spec bagian 10).

Alias model yang tersedia: `company-fast` dan `company-coding` (Terra), `company-reasoning` (Sol, fallback ke `company-coding`).

Ada dua profil, dipilih dengan `ENV`:

| | `ENV=local` (default) | `ENV=vm` |
| --- | --- | --- |
| Upstream | `mock-upstream` (selalu menjawab `mock-ok`) | OpenAI asli |
| Env file | `deploy/env/local.env` (dibuat `make init-local`) | `deploy/env/vm.env` (diisi dari secret manager) |
| Entitlements | `entitlements/local.yaml` | `entitlements/pilot.yaml` |
| Alamat | `http://127.0.0.1:4000` (`LITELLM_PORT`, default 4000), hanya dari `127.0.0.1` | `http://<ip-vm>:4000` (`LITELLM_PORT`), terbuka ke jaringan kantor |
| TLS | tidak ada; TLS diurus DevOps di level jaringan (spec bagian 10) | tidak ada; TLS diurus DevOps di level jaringan (spec bagian 10). Key lewat jaringan kantor tanpa enkripsi |
| Admin UI dan management API | port yang sama (`/ui`), dilindungi master key; hanya dari `127.0.0.1` | port yang sama (`/ui`), dilindungi master key; terbuka ke jaringan kantor |

Semua perintah dijalankan dari root repo. Host hanya butuh Docker (dengan Compose v2), `make`, dan `git`; `gatewayctl` dan pytest berjalan di container `tools`.

## 2. Menyalakan stack lokal

Lakukan sekali per clone:

```sh
make hooks         # aktifkan hook pre-commit
make init-local    # buat deploy/env/local.env berisi secret acak (izin 600)
```

`make init-local` menolak menimpa file yang sudah ada. Simpan cadangan `local.env`: bila `LITELLM_SALT_KEY` hilang, kredensial di database tidak bisa dibaca lagi.

Lalu nyalakan stack dan terapkan entitlements:

```sh
make up            # build image, nyalakan semua service, tunggu sampai healthy (maks. 5 menit), buang container lama (--remove-orphans)
make ps            # semua service Up; litellm-a, litellm-b, postgres, redis, mock-upstream (healthy)
make plan          # tampilkan selisih entitlements/local.yaml dengan isi LiteLLM (exit 2 = ada perubahan)
make apply         # terapkan selisihnya
make plan          # harus "Ringkasan: 0 aksi ..." dengan exit 0
```

Start pertama bisa memakan 1–2 menit karena LiteLLM menjalankan migrasi database di `litellm-a`; `litellm-b` baru menyala setelah `litellm-a` sehat.

`make apply` mencatat operator dari `git config user.email`. Bila kosong, isi manual: `make apply OPERATOR=nama@perusahaan.com`.

## 3. Mencoba request

### Terbitkan key

Key hanya bisa diterbitkan untuk user yang tercantum di file entitlements (di lokal, misalnya `dev1@local.test`). Key mentah keluar sekali ke stdout, jadi tangkap langsung ke variabel shell dan jangan dicetak:

```sh
KEY=$(make -s ctl ARGS='key issue --user dev1@local.test --label coba')
```

Alias key terbentuk dari `<user>-<label>`, di contoh ini `dev1@local.test-coba`. Label tidak boleh berisi spasi.

### Panggil gateway dengan curl

Di profil lokal, `litellm-a` membuka port `LITELLM_PORT` (default 4000) hanya di `127.0.0.1`, lewat HTTP tanpa sertifikat:

```sh
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"company-coding","messages":[{"role":"user","content":"halo"}]}'
```

Jawaban lokal berisi `"content":"mock-ok"` dan usage 1000 token input + 500 token output (sekitar $0,01 per request di Terra). Dengan `"stream": true`, jawaban dikirim sebagai event SSE.

Untuk cek cepat: `/v1/models` mengembalikan daftar alias yang diizinkan untuk key. Tidak ada allowlist path: route manajemen LiteLLM ada di port yang sama dan hanya bisa dipakai dengan master key.

Selesai mencoba, blokir key dan hapus variabelnya:

```sh
make ctl ARGS='key block --alias dev1@local.test-coba'
unset KEY
```

### Memakai OpenCode ke stack lokal (opsional)

Ini hanya untuk memeriksa konfigurasi, karena mock tidak memberikan jawaban yang bermakna dan tidak bisa menjalankan agent. Uji OpenCode yang sebenarnya (T06, T07) dilakukan di VM.

1. Salin `docs/opencode.example.json` dan ganti `baseURL` menjadi `http://127.0.0.1:4000/v1`. Tidak perlu mengubah `/etc/hosts` dan tidak perlu file CA.
2. Jalankan OpenCode dengan `COMPANY_LLM_KEY` diisi key dari langkah di atas.

## 4. Operasi harian

### Perintah `gatewayctl`

| Kebutuhan | Perintah |
| --- | --- |
| Lihat rencana perubahan | `make plan` (atau `make plan ARGS=--json`) |
| Terapkan perubahan | `make apply` |
| Terapkan perubahan destruktif (offboarding, hapus izin) | `make apply ARGS=--confirm` |
| Hapus team yang tidak ada lagi di file | `make apply ARGS='--confirm --prune'` |
| Terbitkan key | `KEY=$(make -s ctl ARGS='key issue --user U --label L')` |
| Daftar key (tanpa key mentah) | `make ctl ARGS='key list'`, bisa difilter `--user U` atau `--team T` |
| Blokir darurat semua key user | `make ctl ARGS='key block --user U'` |
| Blokir satu key | `make ctl ARGS='key block --alias U-L'` |

Untuk VM, tambahkan `ENV=vm` ke setiap perintah, misalnya `make plan ENV=vm`.

Exit code `gatewayctl`:

| Kode | Arti |
| --- | --- |
| 0 | Berhasil, atau `plan` tanpa perubahan |
| 1 | Gagal (pesan ada di stderr) |
| 2 | `plan` menemukan perubahan yang belum diterapkan |
| 3 | LiteLLM tidak bisa dihubungi dan belum ada perubahan yang dijalankan |
| 4 | Ada aksi destruktif tanpa `--confirm`; tidak ada yang dijalankan |

Semua output selain key mentah ditulis ke stderr. Setiap perubahan dicatat di `var/audit.log` (JSONL) beserta operator dan commit file entitlements.

### Mengubah team, member, atau budget

Jangan memanggil management API secara manual. Alurnya selalu:

1. Ubah `entitlements/<profil>.yaml`: tambah member di `members`, ubah `budget`, `rpm_limit`, atau `models`.
2. `make plan` dan tinjau rencananya.
3. `make apply` (tambahkan `ARGS=--confirm` bila plan menandai aksi destruktif).
4. Commit perubahan file entitlements agar audit log menunjuk ke commit yang jelas. Bila file belum di-commit saat apply, audit mencatatnya sebagai `-dirty`.

Menghapus member dari file berarti offboarding: semua key yang diterbitkan `gatewayctl` untuk user itu diblokir. Key yang dibuat di luar `gatewayctl` hanya ditandai di `plan` dan perlu diblokir manual (lihat keputusan Gate 2 di deskripsi PR).

### Log, berhenti, dan menyalakan ulang

```sh
make logs ARGS='--tail 100 litellm-a'   # log satu service
make logs ARGS='-f litellm-a'           # ikuti log litellm-a, replika yang menerima request pengguna
make down                               # matikan stack, volume tetap ada
make up                                 # nyalakan lagi; key, team, dan spend tetap ada
make config                             # validasi konfigurasi compose tanpa mencetak isinya
```

Jangan pernah memakai `docker compose down -v` atau menghapus volume `pgdata`, karena key, team, dan spend ikut hilang. Jangan mengubah `LITELLM_LOG` menjadi `DEBUG`, karena isi request akan tercetak di log.

## 5. Menjalankan test

| Perintah | Butuh stack | Isi |
| --- | --- | --- |
| `make unit` | tidak | Unit test `gatewayctl`, mock upstream, dan konfigurasi deploy |
| `make test` | stack lokal hidup, sudah `make apply` | Unit, integrasi, acceptance T01–T05 dan T08–T10, lalu pemindaian log T10 |
| `make smoke ENV=vm` | stack VM | Smoke T06/T07 ke OpenAI asli (lihat checklist) |

`make test` menjalankan sekitar 25 uji acceptance yang memakai state bersama (budget, rate limit, mock). Jangan menjalankan dua `make test` bersamaan. Baris `T03 spend=...` dan `T05 revocation seconds=...` di output dicatat ke tabel Gate 2 di checklist.

## 6. Persiapan VM sebelum T06, T07, dan T11

Urutan lengkapnya ada di `docs/pilot-checklist.md` bagian 2–5. Hal yang perlu disiapkan sebelum mulai:

- **Akses dan software:** VM dengan Docker (Compose v2), `make`, dan `git`, plus clone repo ini di branch yang akan diuji.
- **Secret:** semua nilai di `deploy/env/vm.env.example`, diambil dari secret manager. `OPENAI_API_KEY` sebaiknya milik OpenAI Project khusus gateway, supaya usage di dashboard OpenAI bisa dicocokkan untuk T11.
- **Jaringan:** port `LITELLM_PORT` (default 4000) terbuka dari jaringan kantor di firewall VM dan belum dipakai aplikasi lain, dan VM bisa keluar ke `api.openai.com`. Bila port 4000 sudah dipakai, isi `LITELLM_PORT` di `vm.env` dengan port kosong; alamat pengguna lalu memuat port itu. Container `tools` memanggil `litellm-a` lewat jaringan Docker, jadi tidak bergantung pada port ini.
- **Operator:** `git config user.email` di VM terisi, atau tambahkan `OPERATOR=...` ke `make apply` dan `make ctl`.
- **Budget uji:** key smoke dibatasi $2 per 30 hari (`entitlements/pilot.yaml`). Naikkan lewat file entitlements bila sesi manual T06/T07 butuh lebih.

Setelah `make up ENV=vm`, cek dari laptop di jaringan kantor:

```sh
curl -sS http://<ip-vm>:4000/health/liveliness                              # 200
curl -sS -o /dev/null -w '%{http_code}\n' http://<ip-vm>:4000/key/list      # 401 (management API butuh master key)
```

Ganti `<ip-vm>` dengan IP VM, dan `4000` dengan `LITELLM_PORT` bila diubah.

Lalu ikuti checklist mulai dari `make plan ENV=vm`.

## 7. Masalah umum

| Gejala | Penyebab dan solusi |
| --- | --- |
| `make up` gagal dengan pesan `... belum diisi` | Variabel di env file kosong. Lokal: jalankan `make init-local`. VM: lengkapi `deploy/env/vm.env`. |
| `make up ENV=vm` gagal dengan `bind: address already in use` | Port `LITELLM_PORT` (default 4000) dipakai aplikasi lain; cek dengan `sudo ss -ltnp \| grep ':4000 '` (ganti port sesuai pesan). Isi `LITELLM_PORT` di `vm.env` dengan port kosong, misalnya `8080`, lalu `make up ENV=vm` lagi. Alamat pengguna dan Admin UI ikut berubah. |
| Port lama (8443, 80, 443) masih dipakai container gateway setelah update | Container `caddy` dari versi lama masih hidup. `make up` (atau `make up ENV=vm`) memakai `--remove-orphans` sehingga container lama dibuang otomatis; jalankan sekali lagi dengan versi repo ini. Volume lama dibiarkan. |
| `make up` timeout menunggu healthy | Lihat `make logs ARGS='--tail 200 litellm-a'`. Penyebab umum: `DATABASE_URL` tidak cocok dengan `POSTGRES_PASSWORD`, atau image belum selesai ditarik. |
| `gatewayctl` exit 3 | LiteLLM belum siap. Tunggu `make ps` menunjukkan healthy, lalu ulangi. |
| `GATEWAYCTL_OPERATOR wajib diisi` | `git config user.email` kosong; tambahkan `OPERATOR=nama@perusahaan.com`. |
| `key issue` menolak user | User belum ada di file entitlements atau belum di-`apply`. |
| 401, 429, 422 `budget_exceeded` | Lihat tabel error di `docs/onboarding.md`. |
