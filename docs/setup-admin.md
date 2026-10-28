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

Hasil yang diharapkan: enam service berstatus `Up`, dan lima di antaranya `(healthy)`:

```
llm-gateway-local-caddy-1           ...  Up ...
llm-gateway-local-litellm-a-1       ...  Up ... (healthy)
llm-gateway-local-litellm-b-1       ...  Up ... (healthy)
llm-gateway-local-mock-upstream-1   ...  Up ... (healthy)
llm-gateway-local-postgres-1        ...  Up ... (healthy)
llm-gateway-local-redis-1           ...  Up ... (healthy)
```

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

Salin sertifikat lokal gateway (sekali saja) supaya HTTPS bisa diverifikasi:

```sh
make local-ca
```

Kirim pertanyaan ke gateway:

```sh
curl -sS --resolve llm.pilot.test:8443:127.0.0.1 --cacert var/caddy-local-root.crt \
  https://llm.pilot.test:8443/v1/chat/completions \
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

Gateway di VM bisa diakses dengan dua cara:

| | Lewat IP (belum ada domain) | Lewat domain |
| --- | --- | --- |
| Alamat untuk pengguna | `https://10.0.0.5/v1` | `https://llm.perusahaan.internal/v1` |
| Alamat admin (hanya dari VPN) | `https://10.0.0.5:8443` | `https://llm-admin.perusahaan.internal` |
| Sertifikat | Dibuat otomatis oleh Caddy; laptop penguji memercayai CA-nya | Sertifikat perusahaan |
| `VM_TLS` di `vm.env` | `internal` | `company` |

Langkah di bawah memakai cara **lewat IP**. Ganti `10.0.0.5` dengan IP VM Anda. Cara pindah ke domain ada di akhir bagian ini.

### B1. Siapkan sebelum mulai

Minta atau siapkan hal berikut:

- [ ] VM Linux dengan Docker (Compose v2), `make`, dan `git` terpasang.
- [ ] IP VM yang bisa dijangkau dari laptop penguji, lewat VPN atau jaringan kantor.
- [ ] Port 80, 443, dan 8443 VM terbuka untuk jaringan itu, dan VM bisa mengakses `api.openai.com`.
- [ ] Rentang IP VPN kantor (`VPN_CIDR`, misalnya `10.8.0.0/16`). Hanya alamat dari rentang ini yang boleh membuka alamat admin.
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
| `VM_TLS` | `internal` |
| `LLM_HOST` | IP VM, misalnya `10.0.0.5` |
| `LLM_ADMIN_HOST` | IP VM dengan port 8443, misalnya `10.0.0.5:8443` |
| `VPN_CIDR` | Rentang IP VPN dari B1. |
| `TLS_CERT_DIR` | Biarkan `/etc/llm-gateway/certs`. Selama memakai IP folder ini kosong, tetapi harus ada (B4). |

Tambahkan juga baris berikut di akhir file, agar test di VM memercayai sertifikat Caddy:

```
GATEWAY_CA_BUNDLE=/repo/var/caddy-vm-root.crt
```

Simpan salinan isi file ini di secret manager atau password manager perusahaan. Bila file ini hilang, data gateway tidak bisa dibuka lagi.

### B4. Siapkan folder sertifikat

```sh
sudo mkdir -p /etc/llm-gateway/certs
```

Folder ini dibiarkan kosong selama memakai IP. Sertifikat perusahaan baru ditaruh di sini saat pindah ke domain.

### B5. Nyalakan gateway dan ambil sertifikat CA

```sh
make up ENV=vm
make ps ENV=vm
make vm-ca ENV=vm
```

Hasil yang diharapkan:

- `make ps` sama dengan A4, tetapi tanpa `mock-upstream` (lima service).
- `make vm-ca` membuat `var/caddy-vm-root.crt`. Ini sertifikat CA publik buatan Caddy, bukan rahasia. Penguji butuh file ini agar laptopnya memercayai gateway. Isinya tetap sama selama volume Caddy tidak dihapus.

Salin file CA ke laptop Anda, misalnya dengan `scp`:

```sh
scp <user>@10.0.0.5:company-ai-platform/var/caddy-vm-root.crt ~/llm-gateway-ca.crt
```

Lalu, dari laptop yang terhubung VPN, cek:

```sh
curl -sS --cacert ~/llm-gateway-ca.crt https://10.0.0.5/health/liveliness
curl -sS --cacert ~/llm-gateway-ca.crt -o /dev/null -w '%{http_code}\n' https://10.0.0.5/key/list
curl -sS --cacert ~/llm-gateway-ca.crt -o /dev/null -w '%{http_code}\n' https://10.0.0.5:8443/health/liveliness
```

Hasil yang diharapkan:

- Perintah pertama: jawaban sukses (kode 200).
- Perintah kedua: `404`. Route admin memang ditutup di alamat pengguna.
- Perintah ketiga: `200` bila IP laptop termasuk `VPN_CIDR`, atau `403` bila tidak.

Kalau gagal:

- `curl: (60)` atau `certificate` error: file CA belum dipakai atau salah. Jalankan ulang `make vm-ca ENV=vm` dan salin lagi.
- `Connection refused` atau timeout: port 443/8443 belum dibuka di firewall VM, atau laptop belum terhubung VPN.

### B6. Daftarkan team dan user pilot

Buka `entitlements/pilot.yaml`. Tambahkan email anggota pilot di bawah `members` pada team yang sesuai, dengan menghapus tanda `#` pada contoh `nama.depan@perusahaan.com`. Lalu:

```sh
make plan ENV=vm
make apply ENV=vm
make plan ENV=vm   # harus: Ringkasan: 0 aksi, tanpa Error 2
```

Commit perubahan file entitlements agar ada jejak siapa yang mengubah apa.

### B7. Siapkan laptop penguji

Lakukan di setiap laptop yang akan memakai OpenCode ke gateway:

1. Simpan file CA dari B5, misalnya di `~/llm-gateway-ca.crt`.
2. Tambahkan ke `~/.zshrc` atau `~/.bashrc`, lalu buka terminal baru:

   ```sh
   export NODE_EXTRA_CA_CERTS="$HOME/llm-gateway-ca.crt"
   ```

   OpenCode membaca variabel ini untuk memercayai CA tambahan.
3. Salin `docs/opencode.example.json` seperti di `docs/onboarding.md`, lalu ganti `baseURL` menjadi `https://10.0.0.5/v1`.
4. Simpan key pengguna sebagai `COMPANY_LLM_KEY` (lihat `docs/onboarding.md`).

### B8. Lanjut ke uji T06, T07, dan T11

Gateway siap. Ikuti `docs/pilot-checklist.md` mulai dari langkah 2.5 (menerbitkan key smoke), lalu bagian 3 sampai 6.

### Nanti: pindah dari IP ke domain

Saat domain dan sertifikat perusahaan sudah ada:

1. Taruh `fullchain.pem` dan `privkey.pem` (mencakup kedua domain) di `/etc/llm-gateway/certs/`.
2. Di `deploy/env/vm.env`: set `VM_TLS=company`, isi `LLM_HOST` dan `LLM_ADMIN_HOST` dengan kedua domain (tanpa port), lalu hapus baris `GATEWAY_CA_BUNDLE`. Bila sertifikat perusahaan diterbitkan CA internal, isi `GATEWAY_CA_BUNDLE` dengan CA itu (lihat `docs/pilot-checklist.md` langkah 2.2).
3. `make up ENV=vm`. Caddy dibuat ulang dengan konfigurasi baru; key, team, dan spend tetap ada.
4. Penguji mengganti `baseURL` ke domain dan boleh menghapus `NODE_EXTRA_CA_CERTS`. Key mereka tetap berlaku.

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
make logs ARGS='-f caddy'               # akses masuk (tekan Ctrl+C untuk berhenti)
```

Referensi lengkap perintah, exit code, dan troubleshooting ada di `docs/operator-guide.md`.
