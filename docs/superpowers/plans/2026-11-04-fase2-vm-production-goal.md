# Goal: jalankan rencana Fase 2 sampai sukses (eksekusi native)

Pakai di sesi Claude Code baru, di root repo, dalam mode auto, setelah PR spec dan plan Fase 2 di-merge ke `main`:

```
/goal execute docs/superpowers/plans/2026-11-04-fase2-vm-production-goal.md
```

Pemilik repo meminta file ini dijalankan dengan eksekusi native: sesi ini sendiri mengerjakan semua task dengan skill `superpowers:executing-plans`, tanpa workflow dan tanpa subagent implementer. Setelah semua task selesai, satu reviewer baru memeriksa seluruh branch.

Rencana lengkapnya ada di `docs/superpowers/plans/2026-11-04-fase2-vm-production.md`, dan Global Constraints di sana berlaku untuk semua langkah. Spec-nya ada di `docs/superpowers/specs/2026-11-04-fase2-vm-production-design.md`.

Run ini hanya memakai stack lokal (`ENV=local`). Tidak ada perintah dengan `ENV=vm`. Langkah di VM dijalankan operator sesuai `docs/gate3-checklist.md` setelah PR implementasi di-merge.

## Selesai bila

Goal tercapai hanya bila **semua** hal berikut terlihat di percakapan sebagai keluaran perintah, dan semuanya dijalankan setelah commit terakhir:

1. `git rev-parse --abbrev-ref HEAD` berbunyi `feat/fase2-vm-production`, dan `git log --oneline main..HEAD` berisi commit Task 1 sampai Task 9, ditambah commit perbaikan bila ada.
2. `make unit` dan `make test` lulus, dengan baris `T03 spend=`, `T05 revocation seconds=`, dan `T10 clean` ditampilkan. Baris T10 menyebut `litellm-a:/metrics` dan `litellm-b:/metrics`.
3. `make test-failure` lulus, dengan baris `T12 behavior=`, `T12 recovery seconds=`, `T13 cached_key_seconds=`, `T13 recovery seconds=`, dan `T15 restore ok` ditampilkan.
4. `make loadtest` lulus, dengan dua baris `T16 concurrency=` (25 dan 50) ditampilkan.
5. Reviewer akhir menyetujui branch. Bila ia menemukan masalah, semua temuan yang dikonfirmasi sudah diperbaiki dalam commit baru, dan butir 2 sampai 4 dijalankan ulang setelahnya.
6. `make ps` menunjukkan semua service healthy, dan `git status --porcelain` tidak mengeluarkan apa-apa.
7. Tidak ada `git push` atau `gh pr create` yang dijalankan.
8. Laporan akhir dengan format di bawah sudah ditulis, dengan `Status: SUKSES`.

## Berhenti tanpa sukses bila

Hentikan run, tulis laporan akhir dengan `Status: BERHENTI` beserta penyebabnya, dan jangan mengakali aturan, bila salah satu ini terjadi:

- Prasyarat di bawah tidak terpenuhi.
- Task 4 Step 6: `test_metrics_accepts_virtual_key` atau `test_scraper_key_cannot_call_models` gagal (spec 5.3). Jangan menonaktifkan autentikasi `/metrics` dan jangan memakai master key.
- Ambang T12, T13, T15, atau T16 tidak tercapai karena perilaku gateway yang sebenarnya, bukan karena bug uji. Catat keluarannya sebagai temuan Gate 3. Ambang tidak boleh dilonggarkan.
- Kegagalan yang sama muncul tiga kali berturut-turut setelah diperbaiki.
- Hook penjaga menolak perintah yang dibutuhkan, dan tidak ada cara lain yang sesuai rencana.
- Sudah 80 giliran.

## Prasyarat

Cek dengan perintah berikut, dan jangan mengubah apa pun untuk meloloskannya:

```sh
git fetch origin
git rev-parse --abbrev-ref HEAD                      # harus main
git status --porcelain                               # harus kosong
git rev-list --count HEAD..origin/main               # harus 0
test -f docs/superpowers/plans/2026-11-04-fase2-vm-production.md && echo plan-ok
git config core.hooksPath                            # harus .githooks
test -f deploy/env/local.env && echo env-ok          # hanya cek keberadaan; isinya tidak dibaca
docker info >/dev/null 2>&1 && echo docker-ok
```

## Langkah

1. **Tulis ulang bagian "Selesai bila"** di atas, apa adanya, di balasan pertama.
2. **Cek prasyarat** dengan perintah di atas. Kalau ada yang gagal, berhenti.
3. **Buat branch:** `git switch -c feat/fase2-vm-production`, lalu `make up` dan `make ps`.
4. **Muat skill `superpowers:executing-plans`**, lalu kerjakan Task 1 sampai Task 9 dari rencana secara berurutan:
   - Setiap step dikerjakan apa adanya, termasuk step "tulis uji yang gagal" dan "jalankan, harapan FAIL". Tampilkan keluaran yang membuktikan FAIL sebelum menulis implementasi.
   - Setiap task diakhiri satu commit lewat hook pre-commit, dengan pesan commit dari rencana.
   - Perintah yang bisa lebih dari 10 menit (`make test`, `make test-failure`, `make loadtest`) dijalankan dengan `run_in_background`, lalu tunggu sampai selesai.
   - Bila sebuah step tidak bisa dijalankan seperti tertulis (nama file, field, atau perilaku LiteLLM berbeda), pilih penyesuaian terkecil yang tetap memenuhi spec dan Global Constraints, lalu catat di pesan commit dan di laporan akhir. Bila penyesuaian itu mengubah perilaku yang dikunci spec, berhenti dan tanyakan.
5. **Jalankan Task 10 Step 1 sampai Step 3.** Step 4 (push dan PR) tidak dijalankan.
6. **Review akhir.** Kirim satu reviewer baru (Agent tool, `subagent_type: "general-purpose"`) dengan brief berikut, tanpa menyertakan kesimpulan Anda sendiri:

   > Review branch `feat/fase2-vm-production` (`git log --oneline main..HEAD`, `git diff main...HEAD`) terhadap spec `docs/superpowers/specs/2026-11-04-fase2-vm-production-design.md` dan plan `docs/superpowers/plans/2026-11-04-fase2-vm-production.md`, termasuk Global Constraints, Review Focus, dan aturan di `CLAUDE.md`. Fokus pada: skrip backup/restore yang bisa kehilangan atau merusak data, skrip uji kegagalan yang bisa meninggalkan stack mati atau menyentuh `ENV=vm`, key mentah atau rahasia yang tertulis ke file, argv, atau log, ambang uji yang dilonggarkan, dan dokumen yang tidak sesuai perintah sebenarnya. Jalankan `make unit` sendiri. Jangan menjalankan `make test`, `make test-failure`, atau `make loadtest`, dan jangan mengubah file apa pun. Laporkan setiap temuan dengan file:baris, skenario kegagalan konkret, dan tingkat keparahan, lalu beri putusan akhir: DISETUJUI atau PERLU PERBAIKAN.

   Periksa setiap temuan terhadap kode sebelum memperbaikinya (skill `superpowers:receiving-code-review`). Perbaiki temuan yang terkonfirmasi dalam commit baru, lalu ulangi Task 10 Step 1 sampai Step 3. Temuan yang Anda tolak dicatat beserta alasannya di laporan akhir.
7. **Tampilkan bukti akhir:**

   ```sh
   git rev-parse --abbrev-ref HEAD; git log --oneline main..HEAD; make ps; git status --porcelain
   ```

8. **Tulis laporan akhir.**

## Aturan selama run

- Jangan push, jangan membuat PR, dan jangan menjalankan amend atau rebase. Push dan PR menunggu izin pemilik repo (rencana Task 10 Step 4).
- Jangan menjalankan perintah apa pun dengan `ENV=vm`, dan jangan menjalankan `make restore` selain lewat `make test-failure` di stack lokal.
- Jangan mengubah spec, rencana, file ini, `docs/LLM_GATEWAY_ARCHITECTURE.md`, atau bagian `docs/LITELLM_IMPLEMENTATION_GUIDE.md` di luar dua baris Task 9.
- Jangan membaca atau mencetak `deploy/env/*.env`. Jangan menulis key mentah ke file, kecuali `var/t10-sentinels.txt` yang sudah ada.
- Jangan menjalankan `make test`, `make test-failure`, dan `make loadtest` bersamaan.
- Jangan pernah `docker compose down -v` atau menghapus volume.
- Bila hook penjaga menolak sebuah perintah, jangan mencari jalan memutar. Ganti pendekatan sesuai rencana, atau berhenti dan laporkan.

## Format laporan akhir

```
Status: SUKSES | BERHENTI
Branch: <git rev-parse --abbrev-ref HEAD>
HEAD: <git rev-parse HEAD>
Commit main..HEAD:
<git log --oneline main..HEAD>
T03: <baris T03>
T05: <baris T05>
T10: <baris T10 clean>
T12: <baris T12 behavior dan T12 recovery>
T13: <baris T13 cached_key_seconds dan T13 recovery>
T15: <baris T15 restore ok>
T16: <dua baris T16 concurrency>
Metrik: <nama family yang dipakai di docs/devops-handoff.md>
Penyesuaian dari rencana: <daftar, atau "tidak ada">
Review akhir: <putusan reviewer; temuan yang diperbaiki; temuan yang ditolak beserta alasan>
Belum dilakukan: push dan PR (butuh izin pemilik repo); langkah VM di docs/gate3-checklist.md (T16 di VM, cron, key scrape, konfirmasi DevOps, T14)
Penyebab berhenti: <hanya bila BERHENTI>
```
