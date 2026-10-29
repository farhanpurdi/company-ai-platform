# Setup dan menjalankan gateway: langkah demi langkah untuk admin

Ikuti dokumen ini dari atas ke bawah. Setiap langkah berisi perintah yang dijalankan dan hasil yang seharusnya muncul. Bila hasilnya berbeda, berhenti dulu dan lihat bagian "Kalau gagal" di langkah itu atau tabel di `docs/operator-guide.md` bagian 7.

Ada tiga bagian:

- **Bagian A: coba di laptop.** Gateway berjalan dengan OpenAI palsu (mock), jadi gratis dan aman. Lakukan ini dulu untuk mengenal cara kerjanya.
- **Bagian B: pasang di VM.** Gateway sungguhan untuk pilot, memakai OpenAI asli.
- **Bagian C: tugas admin sehari-hari.** Menambah user, memberi key, memblokir key.

Istilah yang dipakai:

| Istilah | Arti |
| --- | --- |
| Gateway | Server perantara antara pengguna dan OpenAI. Pengguna tidak pernah memegang key OpenAI. |
| Virtual key | Key pribadi `sk-...` yang diberikan admin ke tiap pengguna. Bisa dibatasi budget dan diblokir kapan saja. |
| Entitlements | File YAML di `entitlements/` yang berisi daftar team, anggota, budget, dan model yang boleh dipakai. |
| `make plan` / `make apply` | Lihat perubahan dari file entitlements, lalu terapkan ke gateway. |

---

## Bagian A: coba di laptop

### A1. Siapkan software

Butuh Docker Desktop (atau Docker Engine dengan Compose v2), `make`, dan `git`. Cek dengan:

```sh
docker --version
docker compose version
make --version
git --version
```

Hasil yang diharapkan: keempat perintah mencetak nomor versi. Pastikan Docker Desktop sedang berjalan (ikon Docker aktif).

Kalau gagal: pasang Docker Desktop dari situs Docker. Di macOS, `make` dan `git` tersedia setelah `xcode-select --install`.

Python dan library lain tidak perlu dipasang. Semuanya berjalan di dalam container.

### A2. Ambil kode

```sh
git clone https://github.com/farhanpurdi/company-ai-platform.git
cd company-ai-platform
make hooks
```

Semua perintah berikutnya dijalankan dari folder ini.

### A3. Buat file rahasia lokal (sekali saja)

```sh
make init-local
```

Hasil yang diharapkan:

```
deploy/env/local.env dibuat (izin 600). Simpan cadangannya: LITELLM_SALT_KEY tidak boleh hilang atau diganti.
```

File ini berisi password acak untuk database, Redis, dan master key gateway. Jangan di-commit, jangan dibagikan, dan jangan dihapus. Bila muncul `Gagal: deploy/env/local.env sudah ada`, berarti langkah ini sudah pernah dilakukan; lanjut ke A4.

### A4. Nyalakan gateway

```sh
make up
```

Langkah pertama butuh beberapa menit karena Docker mengunduh image dan membangun container. Perintah ini menunggu sampai semua service siap.

Cek statusnya:

```sh
make ps
```

Hasil yang diharapkan: lima service, semuanya `Up ... (healthy)`:

```
llm-gateway-local-litellm-a-1       ...  Up ... (healthy)
llm-gateway-local-litellm-b-1       ...  Up ... (healthy)
llm-gateway-local-mock-upstream-1   ...  Up ... (healthy)
llm-gateway-local-postgres-1        ...  Up ... (healthy)
llm-gateway-local-redis-1           ...  Up ... (healthy)
```

Gateway sekarang terbuka di `http://127.0.0.1:4000`, hanya dari laptop ini. Port lain di dalam stack (`litellm-b`, database, Redis) tidak dibuka ke host.

Kalau gagal: lihat log dengan `make logs ARGS='--tail 100 litellm-a'`. Bila hanya belum `healthy`, tunggu satu menit lalu cek lagi.

### A5. Daftarkan team dan user

Gateway yang baru menyala masih kosong. Isi team dan user diambil dari `entitlements/local.yaml`.

Lihat dulu apa yang akan dibuat:

```sh
make plan
```

Hasil yang diharapkan: daftar baris berawalan `+` (akan dibuat) dan ringkasan di akhir, misalnya:

```
+ create_team it-developer
+ add_member it-developer/dev1@local.test
...
Ringkasan: N aksi (0 destruktif), 0 unmanaged, 0 team yatim
make: *** [plan] Error 2
```

Baris `make: *** ... Error 2` (bentuk persisnya tergantung versi make) itu normal: artinya "ada perubahan yang belum diterapkan", bukan kegagalan.

Terapkan:

```sh
make apply
```

Hasil yang diharapkan: daftar yang sama, lalu `Selesai: N aksi diterapkan.`

Pastikan sudah sinkron:

```sh
make plan
```

Hasil yang diharapkan: `Ringkasan: 0 aksi (0 destruktif), ...` tanpa `Error 2`.

Kalau muncul `GATEWAYCTL_OPERATOR wajib diisi`: email git belum diatur. Jalankan `git config user.email "nama@perusahaan.com"` lalu ulangi.

Kalau muncul `Ada aksi destruktif; tidak ada yang dijalankan. Ulangi dengan --confirm.`: belum ada yang berubah. Baca baris bertanda `[destructive]` di atasnya. Di database baru seharusnya tidak ada aksi destruktif sama sekali. Pakai `make apply ARGS=--confirm` hanya bila setiap aksi itu memang diinginkan, misalnya offboarding (Bagian C).

### A6. Buat key dan kirim pertanyaan pertama

Buat key untuk user uji `dev1@local.test`. Key disimpan ke variabel `KEY` agar tidak tampil di layar:

```sh
KEY=$(make -s ctl ARGS='key issue --user dev1@local.test --label coba')
```

Kirim pertanyaan ke gateway:

```sh
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"company-coding","messages":[{"role":"user","content":"halo"}]}'
```

Hasil yang diharapkan: JSON berisi `"content":"mock-ok"`. Karena memakai mock, jawabannya selalu `mock-ok`. Yang penting, request berhasil melewati gateway.

Cek bahwa pemakaian tercatat:

```sh
make ctl ARGS='key list --user dev1@local.test'
```

Hasil yang diharapkan: baris `dev1@local.test-coba ... tidak 0.0100`. Kolom `BLOKIR` berisi `tidak`, dan `SPEND_USD` berisi $0,01 per request.

### A7. Coba blokir key

```sh
make ctl ARGS='key block --alias dev1@local.test-coba'
```

Hasil yang diharapkan: `1 key diblokir.` Bila perintah curl di A6 diulang, gateway sekarang menolak dengan error 401.

```sh
unset KEY
```

### A8. Jalankan semua test (opsional)

```sh
make test
```

Butuh sekitar 5–10 menit. Hasil yang diharapkan: semua test `PASSED` dan perintah selesai tanpa error.

### A9. Mematikan dan menyalakan lagi

```sh
make down   # matikan; data (key, team, spend) tetap tersimpan
make up     # nyalakan lagi kapan saja; tidak perlu init-local atau apply ulang
```

Jangan pernah menjalankan `docker compose down -v` atau menghapus volume Docker, karena semua key, team, dan catatan spend akan hilang.

---

## Bagian B: pasang di VM (pilot dengan OpenAI asli)

Bagian ini memakai pola yang sama dengan Bagian A. Bedanya, semua perintah memakai `ENV=vm` dan rahasianya diisi manual.

Pengguna dan admin terhubung langsung ke container `litellm-a` lewat HTTP, di port `LITELLM_PORT` (default 4000). Tidak ada reverse proxy dan tidak ada sertifikat di VM:

| | Alamat |
| --- | --- |
| Pengguna (`baseURL` OpenCode) | `http://10.0.0.5:4000/v1` |
| Admin UI (login dengan master key) | `http://10.0.0.5:4000/ui` |

> **Peringatan.** Selama pilot, gateway berjalan **tanpa enkripsi** dan **tanpa allowlist path**:
>
> - Virtual key dan master key lewat jaringan tanpa enkripsi. Siapa pun yang bisa menyadap jaringan antara laptop dan VM bisa membacanya.
> - Management API dan Admin UI ada di port yang sama dan terbuka ke jaringan kantor. Master key menjadi satu-satunya pelindung.
>
> Pakai hanya di jaringan kantor, sampai proxy DevOps dipasang di depan VM (spec bagian 10; lihat "Nanti: proxy DevOps di depan VM" di akhir bagian ini).

Ganti `10.0.0.5` dengan IP VM Anda di semua contoh. Bila `LITELLM_PORT` diganti (B3), ganti juga `4000` di semua alamat.

VM yang pernah dipasang dengan versi lama: jangan ulangi B2 dan B3, karena `cp` di B3 menimpa `vm.env` beserta `LITELLM_SALT_KEY`. Cek B1, lalu langsung ke B4.

### B1. Siapkan sebelum mulai

Minta atau siapkan hal berikut:

- [ ] VM Linux dengan Docker (Compose v2), `make`, dan `git` terpasang.
- [ ] IP VM yang bisa dijangkau dari laptop penguji di jaringan kantor.
- [ ] VM bisa mengakses `api.openai.com`.
- [ ] Port `LITELLM_PORT` (default 4000) terbuka dari jaringan kantor di firewall VM.
- [ ] Port itu belum dipakai aplikasi lain di VM. Cek dengan `sudo ss -ltnp | grep ':4000 '`: hasilnya harus kosong. Kalau ada isinya, pilih port kosong lain untuk `LITELLM_PORT` di B3, lalu cek port pengganti itu dengan perintah yang sama.
- [ ] API key OpenAI dari OpenAI Project khusus gateway, supaya biayanya bisa dicocokkan di uji T11.

### B2. Ambil kode di VM

```sh
git clone https://github.com/farhanpurdi/company-ai-platform.git
cd company-ai-platform
git config user.email "nama-admin@perusahaan.com"
```

### B3. Isi file rahasia VM

```sh
cp deploy/env/vm.env.example deploy/env/vm.env
chmod 600 deploy/env/vm.env
```

Buka `deploy/env/vm.env` dengan editor (misalnya `nano deploy/env/vm.env`) dan isi:

| Variabel | Isi |
| --- | --- |
| `LITELLM_MASTER_KEY` | Teks acak berawalan `sk-`. Buat dengan `echo "sk-$(openssl rand -hex 16)"`. |
| `LITELLM_SALT_KEY` | Teks acak lain berawalan `sk-`. **Tidak boleh diganti setelah gateway dipakai.** |
| `POSTGRES_PASSWORD` | Password acak (`openssl rand -hex 16`). |
| `DATABASE_URL` | Ganti bagian `ganti-dari-secret-manager` dengan password yang sama dengan `POSTGRES_PASSWORD`. |
| `REDIS_PASSWORD` | Password acak lain. |
| `OPENAI_API_KEY` | API key OpenAI Project gateway. |
| `LITELLM_PORT` | Biarkan `4000`. Ganti dengan port kosong lain bila port itu sudah dipakai (B1). |

Simpan salinan isi file ini di secret manager atau password manager perusahaan. Bila file ini hilang, data gateway tidak bisa dibuka lagi.

### B4. Bila VM pernah dipasang dengan versi lama (dengan Caddy)

Lewati langkah ini untuk VM baru.

Versi lama memakai container Caddy di depan gateway, dengan beberapa variabel tambahan untuk TLS dan alamat. Sekarang `deploy/env/vm.env` cukup berisi rahasia (`LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_API_BASE`) dan `LITELLM_PORT`.

1. Ambil kode terbaru dengan `git pull`. File `deploy/env/vm.env` yang sudah ada tetap dipakai; jangan menimpanya dengan `vm.env.example`, dan jangan mengganti `LITELLM_SALT_KEY`.
2. Tambahkan baris `LITELLM_PORT=4000` di `deploy/env/vm.env`, atau port lain hasil cek di B1.
3. Baris lain di luar daftar di atas tidak dipakai lagi. Baris itu boleh dihapus, dan tidak mengganggu bila tertinggal.
4. Lanjut ke B5. `make up ENV=vm` membuang container Caddy lama secara otomatis, sehingga port lamanya dilepas.

Volume Docker lama dibiarkan apa adanya. Jangan menghapus volume apa pun: volume `pgdata` berisi key, team, dan spend. Folder sertifikat lama di VM juga tidak dipakai lagi.

Alamat gateway berubah. Penguji yang sudah memakai alamat lama perlu mengganti `baseURL` seperti di B7.

### B5. Nyalakan gateway dan cek dari laptop

```sh
make up ENV=vm
make ps ENV=vm
```

Hasil yang diharapkan: `make ps` sama dengan A4, tetapi tanpa `mock-upstream`. Empat service, semuanya `Up ... (healthy)`: `litellm-a`, `litellm-b`, `postgres`, dan `redis`.

Dari laptop di jaringan kantor, cek:

```sh
curl -sS http://10.0.0.5:4000/health/liveliness
curl -sS -o /dev/null -w '%{http_code}\n' http://10.0.0.5:4000/key/list
```

Hasil yang diharapkan:

- Perintah pertama: `"I'm alive!"` (kode 200).
- Perintah kedua: `401`. Management API butuh master key.

Kalau gagal:

- `make up` gagal dengan `failed to bind port 0.0.0.0:<port>/tcp ... address already in use`: port `LITELLM_PORT` dipakai aplikasi lain. Isi `LITELLM_PORT` di `deploy/env/vm.env` dengan port kosong lain (cek dengan perintah `ss` di B1), lalu jalankan `make up ENV=vm` lagi. Alamat pengguna dan Admin UI ikut berubah.
- `Connection refused` atau timeout: firewall VM belum membuka port `LITELLM_PORT`, alamatnya tidak memakai port itu, atau laptop tidak terhubung ke jaringan kantor.

### B6. Daftarkan team dan user pilot

Buka `entitlements/pilot.yaml`. Tambahkan email anggota pilot di bawah `members` pada team yang sesuai, dengan menghapus tanda `#` pada contoh `nama.depan@perusahaan.com`. Lalu:

```sh
make plan ENV=vm
make apply ENV=vm
make plan ENV=vm   # harus: Ringkasan: 0 aksi, tanpa Error 2
```

Commit perubahan file entitlements agar ada jejak siapa yang mengubah apa.

### B7. Siapkan laptop penguji

Lakukan di setiap laptop yang akan memakai OpenCode ke gateway. Tidak ada file sertifikat yang perlu dipasang.

1. Salin `docs/opencode.example.json` seperti di `docs/onboarding.md`, lalu ganti `baseURL` menjadi `http://10.0.0.5:4000/v1` (dengan port `LITELLM_PORT` bila bukan 4000).
2. Simpan key pengguna sebagai `COMPANY_LLM_KEY` (lihat `docs/onboarding.md`).

Pakai gateway hanya saat laptop terhubung ke jaringan kantor, karena key terkirim tanpa enkripsi.

### B8. Lanjut ke uji T06, T07, dan T11

Gateway siap. Ikuti `docs/pilot-checklist.md` mulai dari langkah 2.5 (menerbitkan key smoke), lalu bagian 3 sampai 6.

### Nanti: proxy DevOps di depan VM

HTTP langsung ke `litellm-a` hanya untuk pilot. Sebelum gateway dipakai lebih luas, DevOps memasang proxy di depan VM yang menyediakan (spec bagian 10):

- TLS, sehingga key tidak lagi lewat jaringan tanpa enkripsi.
- Allowlist tiga path inference: `/v1/chat/completions`, `/v1/models`, dan `/health/liveliness`. Path lain ditolak.
- Management API dan Admin UI hanya bisa dijangkau dari jaringan yang dipercaya.
- Load balancing ke kedua replika, `litellm-a` dan `litellm-b`. Saat ini hanya `litellm-a` yang membuka port ke host; port `litellm-b` dibuka lewat perubahan di repo, bukan dengan mengubah VM langsung.
- Timeout baca minimal 600 detik tanpa buffering, agar jawaban streaming yang panjang tidak terputus.
- Header yang membawa key tidak dicatat di access log proxy.

Setelah proxy siap, pengguna cukup mengganti `baseURL` ke alamat proxy. Key, team, dan spend tidak berubah, dan key pengguna tetap berlaku.

---

## Bagian C: tugas admin sehari-hari

Untuk VM, tambahkan `ENV=vm` ke setiap perintah di bawah.

### Menambah pengguna baru

1. Tambahkan email pengguna di `members` team yang tepat di file entitlements.
2. `make plan`, periksa ada baris `+ add_member ...`.
3. `make apply`.
4. Commit perubahan file.

### Memberi key ke pengguna

```sh
make -s ctl ARGS='key issue --user nama.depan@perusahaan.com --label opencode'
```

Key `sk-...` tampil **sekali** di terminal. Salin langsung ke kanal aman (misalnya fitur berbagi di password manager perusahaan), lalu bersihkan layar terminal dengan `clear`. Jangan kirim lewat chat atau email biasa, dan jangan simpan di file. Kirim juga `docs/onboarding.md` ke pengguna sebagai petunjuk pemakaian.

Bila key hilang, key tidak bisa ditampilkan lagi. Blokir yang lama lalu terbitkan yang baru dengan label lain.

### Melihat key dan pemakaian

```sh
make ctl ARGS='key list'                                  # semua key
make ctl ARGS='key list --user nama.depan@perusahaan.com' # satu pengguna
make ctl ARGS='key list --team it-developer'              # satu team
```

### Memblokir key (key bocor, laptop hilang)

```sh
make ctl ARGS='key block --alias nama.depan@perusahaan.com-opencode'  # satu key
make ctl ARGS='key block --user nama.depan@perusahaan.com'            # semua key pengguna
```

Pemblokiran berlaku seketika.

### Pengguna keluar dari perusahaan (offboarding)

1. Hapus email pengguna dari file entitlements.
2. `make plan`. Baris `- remove_member ...` dan `- block_key ...` ditandai `[destructive]`.
3. `make apply ARGS=--confirm`.
4. Commit perubahan file.

### Mengubah budget atau model yang boleh dipakai

Ubah `budget`, `rpm_limit`, atau `models` di file entitlements, lalu `make plan` dan `make apply`. Jangan mengubahnya lewat dashboard atau `curl` ke API admin, karena perubahan itu akan ditimpa lagi oleh `make apply` berikutnya.

### Melihat log

```sh
make logs ARGS='--tail 100 litellm-a'   # log gateway
make logs ARGS='-f litellm-a'           # ikuti log secara langsung (tekan Ctrl+C untuk berhenti)
```

Referensi lengkap perintah, exit code, dan troubleshooting ada di `docs/operator-guide.md`.
