# Goal: jalankan rencana remove-caddy sampai sukses

Pakai di sesi Claude Code baru, di root repo, dalam mode auto:

```
/goal execute docs/superpowers/plans/2026-10-29-remove-caddy-goal.md
```

Pemilik repo meminta file ini dijalankan, termasuk saved workflow `remove-caddy`. Rencana lengkapnya ada di `docs/superpowers/plans/2026-10-29-remove-caddy.md`, dan Global Constraints di sana berlaku untuk semua langkah.

## Selesai bila

Goal tercapai hanya bila **semua** hal berikut terlihat di percakapan sebagai keluaran perintah:

1. `cat var/remove-caddy-success/result` berbunyi `SUKSES remove-caddy <sha>`, dan `<sha>` sama dengan keluaran `git rev-parse HEAD` yang ditampilkan sesudahnya.
2. `git log --oneline main..HEAD` ditampilkan, dan berisi commit Task 1 sampai Task 6 di atas commit Task 0 (`chore: Claude hooks that block CLAUDE.md violations before they run`).
3. `git status --porcelain` tidak mengeluarkan apa-apa.
4. Tidak ada `git push` atau `gh pr create` yang dijalankan.
5. Laporan akhir dengan format di bawah sudah ditulis, dengan `Status: SUKSES`.

## Berhenti tanpa sukses bila

Hentikan run, tulis laporan akhir dengan `Status: BERHENTI` beserta penyebabnya, dan jangan mengakali gerbang, bila salah satu ini terjadi:

- Prasyarat di bawah tidak terpenuhi.
- Workflow berhenti dengan `Task <n> not approved after 3 rounds`.
- `GAGAL` yang sama muncul tiga kali berturut-turut, atau agen verifikasi menyatakan gerbang itu sendiri keliru.
- Hook penjaga menolak perintah yang dibutuhkan, dan tidak ada cara lain yang sesuai rencana.
- Sudah 40 giliran.

## Prasyarat

Cek dengan perintah berikut, dan jangan mengubah apa pun untuk meloloskannya:

```sh
git rev-parse --abbrev-ref HEAD          # harus feat/remove-caddy
git status --porcelain                   # harus kosong
test -f .claude/settings.json && test -f .claude/settings.local.json && test -x .claude/hooks/remove-caddy-success.sh && echo hooks-ok
test -f ~/.claude/workflows/remove-caddy.js && echo workflow-ok
test -f deploy/env/local.env && echo env-ok   # hanya cek keberadaan; isinya tidak dibaca
docker info >/dev/null 2>&1 && echo docker-ok
```

## Langkah

1. **Tulis ulang bagian "Selesai bila"** di atas, apa adanya, di balasan pertama.
2. **Cek prasyarat** dengan perintah di atas. Kalau ada yang gagal, berhenti.
3. **Aktifkan gerbang sukses:** `mkdir -p var && touch var/remove-caddy.goal`.
4. **Jalankan saved workflow `remove-caddy`** (Workflow tool, `name: "remove-caddy"`), lalu tunggu notifikasi selesai. Selama workflow berjalan, jangan mengerjakan task sendiri dan jangan menjalankan `make test`.
5. **Tampilkan hasil workflow.** Kalau workflow berhenti dengan error, tampilkan pesannya dan berhenti.
6. **Jalankan gerbang:** `.claude/hooks/remove-caddy-success.sh --now; echo "exit=$?"` dengan `run_in_background` (bisa lebih dari 10 menit). Setelah selesai, tampilkan:

   ```sh
   cat var/remove-caddy-success/result; git rev-parse HEAD; git log --oneline main..HEAD; git status --porcelain
   ```

   Kalau hasilnya `GAGAL`:
   - baca log yang disebut;
   - perbaiki penyebabnya dalam commit baru, sesuai task terkait dan Global Constraints di rencana;
   - ulangi langkah 6, paling banyak tiga kali untuk `GAGAL` yang sama.
7. **Ambil angka untuk laporan:**

   ```sh
   grep -E 'T03 spend=|T05 revocation seconds=|T10 clean' var/remove-caddy-success/make-test.log
   tail -n 3 var/remove-caddy-success/vm-smoke.log
   ```

8. **Matikan gerbang:** `rm -f var/remove-caddy.goal`.
9. **Tulis laporan akhir.**

## Aturan selama run

- Jangan push, jangan membuat PR, dan jangan menjalankan amend atau rebase. Push dan PR menunggu izin pemilik repo (rencana Task 7 Step 2).
- Jangan mengubah `.claude/hooks/remove-caddy-success.sh`, `.claude/settings.local.json`, `.claude/settings.json`, file ini, atau spec.
- Jangan membaca atau mencetak `deploy/env/*.env`.
- Jangan menjalankan dua `make test` bersamaan, termasuk saat workflow masih berjalan.
- Bila hook penjaga menolak sebuah perintah, jangan mencari jalan memutar. Ganti pendekatan sesuai rencana, atau berhenti dan laporkan.

## Format laporan akhir

```
Status: SUKSES | BERHENTI
Gerbang: <isi var/remove-caddy-success/result>
HEAD: <git rev-parse HEAD>
Commit main..HEAD:
<git log --oneline main..HEAD>
T03: <baris T03>
T05: <baris T05>
T10: <baris T10 clean>
Smoke VM: <ringkasan pytest dari vm-smoke.log>
Belum dilakukan: push dan PR (butuh izin pemilik repo)
Penyebab berhenti: <hanya bila BERHENTI>
```
