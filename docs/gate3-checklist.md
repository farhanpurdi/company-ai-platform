# Checklist Gate 3: produksi di VM

Dasar perintah dan troubleshooting ada di `docs/operator-guide.md`. Semua perintah dijalankan dari root repo. Spec: `docs/superpowers/specs/2026-11-04-fase2-vm-production-design.md`. Syarat Gate 2 (`docs/pilot-checklist.md`) sudah lulus.

Jangan menjalankan `make down -v`, `docker compose down -v`, atau menghapus volume. `make restore` di VM hanya atas permintaan pemilik repo.

## 1. Deploy Fase 2 ke VM

1. `git pull` di VM, lalu `make up ENV=vm`.
2. `make up` tidak menyalakan ulang replika bila hanya `deploy/litellm/config.yaml` yang berubah (file itu di-mount, dan LiteLLM membacanya saat start). Nyalakan ulang kedua replika agar `/metrics` aktif. Ini memutus request yang sedang berjalan sebentar, jadi lakukan di luar jam kerja. Volume tidak disentuh:

   ```sh
   docker compose -p llm-gateway-vm -f deploy/compose.yaml -f deploy/compose.vm.yaml --env-file deploy/env/vm.env up -d --force-recreate --no-deps --wait litellm-a litellm-b
   ```

3. `make plan ENV=vm`: harus memuat `+ add_member member:it-developer/prometheus` dan tanpa aksi destruktif. Lalu `make apply ENV=vm`, dan `make plan ENV=vm` lagi harus exit 0.
4. Terbitkan key scrape (role admin read-only diatur saat key terbit):

   ```sh
   make -s ctl ENV=vm ARGS='key issue --user prometheus --label scrape'
   ```

   Key hanya tampil sekali. Kirim ke DevOps lewat kanal aman (`docs/devops-handoff.md`), jangan ditulis ke file atau chat, lalu jalankan `clear`.
5. Cek dari VM: `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4000/metrics/` tanpa key harus 401.

## 2. Backup

1. Jalankan sekali manual: `make -s backup ENV=vm`. Harapan: satu path `var/backups/litellm-<waktu>.dump` tercetak, dan `ls -l var/backups` menampilkan `-rw-------`. Ini membuat `var/backups/`; cron memakai redirect ke folder itu, jadi jalankan langkah ini sebelum crontab.
2. Pasang crontab sekali (`docs/setup-admin.md` B9), dengan `PATH`:

   ```
   PATH=/usr/local/bin:/usr/bin:/bin
   15 2 * * * cd <repo> && make -s backup ENV=vm >> var/backups/backup.log 2>&1
   ```

3. Keesokan harinya cek `var/backups/backup.log` dan dump baru pukul 02:15 UTC.

## 3. T12, T13, T15 (stack lokal, mock)

`make test-failure` hanya untuk `ENV=local`: skrip menolak profil lain dan mematikan Redis/Postgres sementara. Jalankan di laptop atau di VM dengan stack lokal (bagian 4), tidak bersamaan dengan `make test` atau `make loadtest`.

```sh
make up
make test-failure
```

Salin baris berikut ke tabel hasil (bagian 7): `T12 behavior=`, `T12 recovery seconds=`, `T13 cached_key_seconds=`, `T13 recovery seconds=`, dan `T15 restore ok`. Batas: T12 dan T13 pulih ≤ 120 detik, key T13 yang di-cache ditolak ≤ 300 detik. Hasil di luar batas dicatat sebagai temuan Gate 3; ambangnya tidak diubah.

## 4. T16 di VM (angka resmi)

Dijalankan di luar jam kerja. Stack lokal memakai project dan volume sendiri (`llm-gateway-local`), tidak menyentuh stack `llm-gateway-vm`, dan memakai mock sehingga tidak ada biaya OpenAI.

1. `make init-local` bila `deploy/env/local.env` belum ada.
2. Operator sendiri mengubah `LITELLM_PORT=4100` di `deploy/env/local.env` (port 4000 dipakai produksi).
3. `make up`, `make apply`, lalu `make loadtest`.
4. `make down` (tanpa `-v`).
5. Harapan: dua baris `T16 concurrency=25 ...` dan `T16 concurrency=50 ...`, masing-masing `errors=0` dan `p95_ttft_overhead_s` ≤ 1.0. Salin ke tabel hasil.
6. **Cek manual rate limit OpenAI:** jumlahkan `rpm_limit` semua team di `entitlements/pilot.yaml` (saat ini 600 + 300 = 900 untuk team aktif; hitung ulang bila berubah) dan bandingkan dengan rate limit tier organisasi OpenAI untuk Terra dan Sol. Lulus bila di bawah limit organisasi, atau ada keputusan tertulis bila tidak.

## 5. T14

Menunggu load balancing dari DevOps (`docs/devops-handoff.md`). Langkah uji ditulis di sini saat alamat load balancer tersedia, mengikuti alamat yang diberikan DevOps.

## 6. Konfirmasi DevOps

Semua butir di `docs/devops-handoff.md` bagian 5 terisi: proxy dan load balancing, Prometheus mengambil `/metrics/` dengan key scrape, dashboard dan alert aktif, cek `/health/liveliness` dari luar, dan `var/backups/` tersalin keluar VM.

## 7. Tabel hasil

| Uji | Hasil | Tanggal | Operator |
| --- | --- | --- | --- |
| T12 (Redis mati) | | | |
| T13 (Postgres mati) | | | |
| T14 (load balancing) | menunggu DevOps | | |
| T15 (backup dan restore) | | | |
| T16 25 stream | | | |
| T16 50 stream | | | |
| T16 cek manual rate limit OpenAI | | | |
| Backup cron berjalan | | | |
| Konfirmasi DevOps | | | |
