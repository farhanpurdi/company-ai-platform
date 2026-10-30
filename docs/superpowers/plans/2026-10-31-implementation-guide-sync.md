# Sinkronisasi LITELLM_IMPLEMENTATION_GUIDE.md Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/LITELLM_IMPLEMENTATION_GUIDE.md` (selanjutnya "guide") sesuai dengan repo dan keputusan pilot, memuat rencana tata kelola harga dan Fase 4, dengan salinan konfigurasi yang dijaga `make unit`.

**Architecture:** Hanya dokumen yang berubah, ditambah satu tes statis. Salinan utuh file repo di guide diberi penanda `<!-- salinan: <path> -->`, dan `deploy/tests/test_doc_copies.py` membandingkannya dengan file aslinya. Bagian lain guide disunting langsung sesuai spec.

**Tech Stack:** Markdown, pytest (container `tools`, lewat `make unit`).

**Spec:** `docs/superpowers/specs/2026-10-31-implementation-guide-sync-design.md`

## Global Constraints

- Branch `docs/implementation-guide-sync` (PR #12). Satu commit per task; pre-commit menjalankan `make unit`, jangan `--no-verify`.
- `docs/*.md` berbahasa Indonesia; identifier dan komentar kode berbahasa Inggris.
- Jangan ubah kode gateway, `deploy/litellm/config.yaml`, `deploy/compose*.yaml`, `entitlements/*.yaml`, atau `docs/LLM_GATEWAY_ARCHITECTURE.md`.
- Kriteria Gate 1, Gate 2, Gate 3, dan Go-live di tabel gate guide tidak diubah; hanya baris Gate 4 yang ditambahkan.
- Salinan utuh: penanda `<!-- salinan: <path> -->` di satu baris, langsung diikuti baris pembuka fence; isi blok sama persis dengan file, termasuk newline terakhir.
- Item checklist dicentang (`- [x]`) hanya bila ada bukti di repo (spec pilot, `docs/pilot-checklist.md`, PR). Daftar persisnya ada di Task 2.
- Jangan tulis email orang di dokumen; pakai placeholder `nama.depan@perusahaan.com`.
- Harga (tier Standard per 1M token, input / input cache / output): Terra $2 / $0.20 / $12, Sol $4 / $0.40 / $20; harga Sol promo sampai setidaknya 2026-11-21.
- Sekring batas belanja di provider: jumlah budget bulanan semua team yang memakai provider itu + 10–20%.
- Ambang rekonsiliasi: selisih > 5%.

## Review Focus

- Spec memuat contoh penanda `<!-- salinan: deploy/litellm/config.yaml -->` berisi placeholder. Tes hanya memindai `docs/*.md` tingkat atas, jadi spec di `docs/superpowers/specs/` tidak ikut; `make unit` di Task 1 Step 7 membuktikannya.
- Penanda yang terpisah baris kosong dari fence-nya tidak dikenali regex. Untuk keempat salinan guide, `test_guide_carries_every_copy` menangkapnya.
- Pembaca menyalin perintah §5.4 di VM: setiap perintah memakai `ENV=vm`, dan `key issue` memakai `make -s` agar stdout hanya berisi key.
- Sisa instruksi lama: kata "reload", `curl` ke `/team/new`, `/team/member_add`, `/key/generate`, `/key/block`, `llm.perusahaan.internal`, dan harga lama. Diperiksa dengan `grep` di Task 2 Step 5 dan Task 3 Step 6.
- Setiap `- [x]` baru di Fase 0–1 harus punya bukti dari daftar di Task 2 Step 3.

---

### Task 1: Tes salinan dan salinan konfigurasi di §5.1–§5.3 dan §5.5

**Files:**
- Create: `deploy/tests/test_doc_copies.py`
- Modify: `docs/LITELLM_IMPLEMENTATION_GUIDE.md` §5.1 (baris 120–130), §5.2 (132–163), §5.3 (165–199), §5.5 (260–284)
- Modify: `docs/operator-guide.md:157`

**Interfaces:**
- Produces: penanda `<!-- salinan: <path> -->` dan tes yang menjaganya; task lain tidak menyentuh blok bertanda.

- [ ] **Step 1: Tulis tes yang gagal**

```python
"""Verbatim copies of repo files in docs/*.md stay identical to the files (spec 2026-10-31, 4.4)."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUIDE = "docs/LITELLM_IMPLEMENTATION_GUIDE.md"
GUIDE_COPIES = {"deploy/litellm/config.yaml", "deploy/compose.yaml", "deploy/compose.vm.yaml", "docs/opencode.example.json"}
# The marker line, then the fence opening on the very next line, then the copy.
COPY = re.compile(r"^<!-- salinan: (?P<path>\S+) -->\n```[a-z]*\n(?P<body>.*?)^```$", re.M | re.S)
DOCS = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "docs").glob("*.md"))


def _copies(doc: str) -> list[tuple[str, str]]:
    return [(m["path"], m["body"]) for m in COPY.finditer((REPO / doc).read_text(encoding="utf-8"))]


def test_guide_carries_every_copy():
    assert {path for path, _ in _copies(GUIDE)} == GUIDE_COPIES


@pytest.mark.parametrize("doc", DOCS)
def test_copies_match_their_files(doc):
    stale = [path for path, body in _copies(doc) if body != (REPO / path).read_text(encoding="utf-8")]
    assert stale == [], f"{doc}: salinan berbeda dari file aslinya; salin ulang isinya"
```

- [ ] **Step 2: Jalankan dan pastikan gagal**

Run: `docker run --rm --user $(id -u):$(id -g) -v "$PWD:/repo" -w /repo llm-gateway-tools pytest -p no:cacheprovider deploy/tests/test_doc_copies.py -q`
Expected: `test_guide_carries_every_copy` FAIL (`set() == {...}`); tes per dokumen lulus.

- [ ] **Step 3: §5.2 `config.yaml`**

Ganti blok YAML dengan penanda dan salinan utuh `deploy/litellm/config.yaml`, diawali kalimat "Salinan persis `deploy/litellm/config.yaml`; `make unit` gagal bila berbeda." Ganti kalimat "Setelah deploy, reload model cost map …" dengan: harga per token dipin di config ini (§3.1); gateway tidak memakai cost map yang diunduh (`LITELLM_LOCAL_MODEL_COST_MAP=True`), jadi tidak ada langkah memuat ulang harga dari Admin UI; perubahan harga mengikuti `docs/operator-guide.md`, "Mengubah harga model". Jangan pakai kata "reload".

- [ ] **Step 4: §5.3 Compose**

Judul menjadi `### 5.3 Compose untuk pilot`. Kalimat pembuka: `make up ENV=vm` menjalankan `docker compose` dengan `deploy/compose.yaml`, overlay `deploy/compose.vm.yaml`, dan `deploy/env/vm.env`. Lalu dua salinan bertanda: `deploy/compose.yaml` dan `deploy/compose.vm.yaml`. Ganti paragraf reverse proxy dengan daftar syarat proxy DevOps dari spec pilot §10: TLS; allowlist path inference (`/v1/chat/completions`, `/v1/models`, `/health/liveliness`); management API dan Admin UI hanya dari jaringan tepercaya; load balancing ke kedua replika; timeout baca minimal 600 detik tanpa buffering; header yang membawa key tidak dicatat di access log.

- [ ] **Step 5: §5.5 OpenCode dan §5.1 Env**

§5.5: ganti blok JSON dengan salinan bertanda `docs/opencode.example.json`; kalimat penutup menjadi: template ini dipakai `docs/onboarding.md`; ganti `<ip-vm>` dengan alamat gateway.

§5.1: tambahkan lima baris ini di akhir tabel (tanpa baris judul):

| Variabel | Fungsi | Catatan |
| --- | --- | --- |
| `LITELLM_LOCAL_MODEL_COST_MAP` | `True` | Harga dan batas output dari config dan image yang dipin; cost map tidak diunduh dari GitHub |
| `OPENAI_API_BASE` | Endpoint OpenAI | VM `https://api.openai.com/v1`; lokal mock `http://mock-upstream:8080/v1` |
| `LITELLM_PORT` | Port `litellm-a` di host | Default 4000 |
| `LITELLM_LOG` | `INFO` | Jangan `DEBUG`: body request tercetak di log |
| `JSON_LOGS` | `True` | Log terstruktur |

- [ ] **Step 6: Kalimat di `docs/operator-guide.md:157`**

Tambahkan di akhir langkah 2: "`make unit` juga gagal sampai salinan `config.yaml` di `docs/LITELLM_IMPLEMENTATION_GUIDE.md` bagian 5.2 ikut diperbarui."

- [ ] **Step 7: Jalankan `make unit`**

Run: `make unit`
Expected: semua lulus, termasuk `test_doc_copies.py` (spec di `docs/superpowers/specs/` tidak dipindai).

- [ ] **Step 8: Buktikan tes menangkap salinan basi**

Ubah satu karakter di salinan `config.yaml` di guide, jalankan perintah Step 2. Expected: FAIL `docs/LITELLM_IMPLEMENTATION_GUIDE.md: salinan berbeda …`. Kembalikan, lalu pastikan `git diff` hanya berisi perubahan Step 3–6.

- [ ] **Step 9: Commit**

```bash
git add deploy/tests/test_doc_copies.py docs/LITELLM_IMPLEMENTATION_GUIDE.md docs/operator-guide.md
git commit -m "docs: guide carries exact copies of config, compose and the OpenCode template, checked by make unit"
```

### Task 2: Sinkronisasi header, §1, §2, §5.4, Fase 0–1, §7, §8.1–8.2, §10

**Files:**
- Modify: `docs/LITELLM_IMPLEMENTATION_GUIDE.md` (header baris 1–8, §1, §2, §5.4, §6 Fase 0–1, §7 baris T11, §8.1, §8.2, §10)

**Interfaces:**
- Consumes: §5.3 dari Task 1 (dirujuk dari §2).
- Produces: item Fase 0 "budget dan alert di level OpenAI Project" dan item Fase 1 "Reload model cost map" dibiarkan apa adanya untuk Task 3.

- [ ] **Step 1: Header, §1, §2**

Header: tambahkan baris `Diperbarui: 31 Oktober 2026 (spec docs/superpowers/specs/2026-10-31-implementation-guide-sync-design.md)` dan `Keputusan pilot: docs/superpowers/specs/2026-10-27-litellm-pilot-design.md`.

§1 tabel:
- Baris Deploy: "Pilot: Docker Compose di 1 VM, dua replika (`litellm-a`, `litellm-b`), HTTP langsung ke `litellm-a`; TLS dan proxy oleh DevOps sebelum dipakai luas. Produksi: Kubernetes + Helm, minimal 2 replika".
- Baris baru **Harga**: "Dipin per token di `deploy/litellm/config.yaml` (input, input cache, output); cost map tidak diunduh. Lihat §3.1".
- Baris baru **Budget**: "Fail-closed juga untuk budget (`fail_closed_budget_enforcement: true`): request yang taksiran biaya terburuknya tidak muat di sisa budget ditolak".

§2: setelah diagram, tambahkan catatan "Kondisi pilot (spec pilot §10)": pengguna terhubung langsung ke `litellm-a` lewat HTTP di `LITELLM_PORT`, tanpa ingress TLS, allowlist path, dan pembatasan admin ke VPN; management API dan Admin UI hanya dilindungi master key; kontrol itu kembali saat proxy DevOps dipasang (§5.3).

- [ ] **Step 2: §5.4 Provisioning**

Judul tetap. Ganti seluruh isi dengan:
1. Paragraf: team, member, budget, dan izin alias dideklarasikan di `entitlements/<profil>.yaml` dan diterapkan dengan `gatewayctl` lewat `make`; jangan `curl` manual ke management API untuk perubahan itu; `gatewayctl` memanggil endpoint yang sama dan mencatat audit di `var/audit.log` dengan operator dari `git config user.email` atau `OPERATOR=`.
2. "Contoh (isi terkini di `entitlements/pilot.yaml`):" lalu blok YAML team `it-developer` dari `entitlements/pilot.yaml` dengan satu member `nama.depan@perusahaan.com` (tanpa akun smoke, tanpa penanda salinan).
3. Blok perintah:

```sh
make plan ENV=vm      # exit 2 = ada perubahan; tinjau dulu
make apply ENV=vm     # ARGS=--confirm bila plan menandai aksi destruktif
make -s ctl ENV=vm ARGS='key issue --user nama.depan@perusahaan.com --label opencode'
make ctl ENV=vm ARGS='key block --user nama.depan@perusahaan.com'   # atau --alias <user>-<label>
```

4. Rujukan: detail di `docs/operator-guide.md` bagian 4 dan `docs/setup-admin.md` Bagian C.

- [ ] **Step 3: §6 Fase 0–1 (kecuali item harga untuk Task 3)**

Fase 0:
- `[ ]` Kunci keputusan … — tambahkan "(nilai sementara: spec pilot §10; konfirmasi di `docs/pilot-checklist.md` bagian 1)".
- `[x]` Konfirmasi ID model persis — bukti: T06 dan T07 lulus terhadap OpenAI asli (`docs/pilot-checklist.md` bagian 6).
- `[ ]` Tetapkan toleransi overshoot … — tambahkan "(sementara 10% dan 5 menit)".
- Item domain dan TLS diganti: `[ ]` TLS dan domain disediakan proxy DevOps sebelum gateway dipakai luas (keputusan 2026-10-29, spec pilot §10).
- `[x]` Pilih versi LiteLLM dan pin ke digest — tambahkan "(`v1.106.4@sha256:c169fb3a…`, `deploy/compose.yaml`)".
- Item lain tetap `[ ]` tanpa perubahan.

Fase 1 Setup:
- `[x]` Deploy Docker Compose (bagian 5.3) di VM: dua replika, HTTP langsung ke `litellm-a`; proxy DevOps menyusul.
- `[x]` Terapkan `config.yaml` (bagian 5.2) dengan 3 alias.
- `[x]` Response caching mati; Redis hanya untuk counter dan rate limit.
- `[x]` `LITELLM_MODE=PRODUCTION` sejak awal.
- Item VPN diganti: `[ ]` Admin UI dan management API hanya dari jaringan tepercaya; ditunda ke proxy DevOps, selama pilot hanya dilindungi master key (spec pilot §10).
- `[x]` Buat team pilot: IT/Developer + 1 team non-teknis (`entitlements/pilot.yaml`: `it-developer`, `finance`).
- `[ ]` Provision 5–10 pengguna pilot (baru akun smoke).
- `[x]` Logging metadata aktif, tanpa prompt/output dan key mentah (T10 lulus).
- `[x]` Siapkan template OpenCode dan panduan onboarding (`docs/opencode.example.json`, `docs/onboarding.md`).

Setelah baris "Uji: jalankan T01–T11 …", tambahkan: "Status Gate 2 per 31 Oktober 2026: T01–T10 lulus, T11 menunggu diulang setelah harga diperbarui (`docs/pilot-checklist.md` bagian 6)."

- [ ] **Step 4: §7 T11, §8.1, §8.2, §10**

§7 baris T11, kolom Langkah: "Snapshot spend gateway (`tests/smoke/spend_report.py`) sebelum dan sesudah uji, pada hari UTC tanpa pemakaian dengan harga lama; bandingkan dengan biaya harian OpenAI Project (`docs/pilot-checklist.md` bagian 5)".

§8.1 Onboarding: (1) user di grup IdP yang benar; (2) tambahkan email di `members` team di `entitlements/<profil>.yaml`, `make plan`, `make apply`, commit; (3) `make -s ctl ARGS='key issue --user … --label opencode'`; (4) kirim key lewat kanal aman beserta `docs/onboarding.md`; (5) audit tercatat otomatis di `var/audit.log`.

§8.2 Offboarding: kalimat "Menonaktifkan akun SSO tidak mencabut virtual key" tetap. Langkah: (1) hapus member dari file entitlements; (2) `make plan` menandai aksi destruktif, lalu `make apply ARGS=--confirm` memblokir semua key yang diterbitkan `gatewayctl` untuk user itu; (3) key buatan di luar `gatewayctl` hanya ditandai `plan`, blokir dengan `key block --alias`; (4) verifikasi key lama ditolak di kedua replika (seperti T05); (5) audit tercatat di `var/audit.log`, commit perubahan file.

§10: tandai `- [x]` "Generasi model …" dengan jawaban "Rilis awal memakai `gpt-5.6-terra` dan `gpt-5.6-sol` (T06, T07 lulus terhadap OpenAI asli)". Item toleransi dan target pencabutan tetap `- [ ]`, tambahkan "Nilai sementara: 10% dari limit dan 5 menit (spec pilot §10); menunggu konfirmasi Gate 1". Item lain tetap.

- [ ] **Step 5: Verifikasi**

Run: `grep -nE '/team/new|/team/member_add|/key/generate|/key/block|llm\.perusahaan\.internal' docs/LITELLM_IMPLEMENTATION_GUIDE.md`
Expected: tidak ada output.
Run: `make unit`
Expected: lulus.

- [ ] **Step 6: Commit**

```bash
git add docs/LITELLM_IMPLEMENTATION_GUIDE.md
git commit -m "docs: guide matches the pilot as built (two replicas, entitlements flow, Gate 2 status)"
```

### Task 3: Tata kelola harga

**Files:**
- Modify: `docs/LITELLM_IMPLEMENTATION_GUIDE.md` (§3, §6 Fase 0–3, §8, §9)

**Interfaces:**
- Consumes: item Fase 0 OpenAI Project dan item Fase 1 "Reload model cost map" yang dibiarkan Task 2.
- Produces: `### 3.1 Tata kelola harga` dan runbook `### 8.7 Perubahan harga`, dirujuk Task 4.

- [ ] **Step 1: §3.1**

Tambahkan `### 3.1 Tata kelola harga` setelah "Aturan katalog" berisi tiga prinsip spec bagian 4.2 (harga dipin dan berubah lewat PR, tidak di bawah harga provider, tanggal akhir promo dicatat; prioritas sesuai arah perubahan; gateway satu-satunya batas per team, batas di provider sebagai sekring dengan rumus di Global Constraints, catat bila provider hanya alert).

- [ ] **Step 2: Item checklist Fase 0–3**

- Fase 0: item OpenAI Project menjadi `[ ]` "Pasang batas belanja dan alert di level OpenAI Project sebagai sekring: jumlah budget bulanan semua team + 10–20%; catat bila hanya alert (§3.1)".
- Fase 1: item "Reload model cost map" diganti dua item: `[x]` "Harga dipin di `config.yaml` beserta harga cache; cost map dari image (PR #10)" dan `[ ]` "Verifikasi harga dicatat di kolom Gate 1 `docs/pilot-checklist.md`".
- Fase 2: tambahkan subjudul "Harga:" dengan `[ ]` "Cek ulang harga Sol pada 21 November 2026 (akhir promo); ubah lewat runbook 8.7 bila berubah".
- Fase 3 Governance: tambahkan `[ ]` rekonsiliasi bulanan manual (spend gateway dibanding tagihan provider; selisih > 5% berarti harga ditinjau; hasil dicatat) dan `[ ]` cek perubahan harga otomatis (job terjadwal tanpa secret, misalnya GitHub Actions, membandingkan harga di config dengan cost map LiteLLM terbaru dan membuat issue pengingat bila berbeda; job tidak mengubah config). Pada item "Jadwal: rotasi …", tambahkan "review harga bersama rekonsiliasi bulanan".

- [ ] **Step 3: Runbook 8.7**

Tambahkan `### 8.7 Perubahan harga` setelah 8.6: (1) harga naik diterapkan sebelum tanggal berlaku, harga turun tidak mendesak; (2) ubah ketiga harga di `config.yaml` lewat PR, `make unit` dan `make test`; (3) di VM: `git pull`, lalu `--force-recreate` kedua replika; (4) verifikasi harga yang berlaku; (5) catat tanggal berlaku dan sumbernya. Rujuk `docs/operator-guide.md`, "Mengubah harga model", untuk perintah lengkap.

- [ ] **Step 4: §9 Risiko**

- Baris baru setelah "Biaya Sol tinggi …": "Harga provider berubah atau promo berakhir" | "Spend tidak cocok dengan tagihan; bila harga naik, budget bocor sebesar selisihnya" | "Harga dipin dan direview (§3.1, runbook 8.7), rekonsiliasi bulanan, cek perubahan harga otomatis, sekring di provider".
- Baris "Budget overshoot pada request paralel": tambahkan di mitigasi "`fail_closed_budget_enforcement`; T03 terukur -4%".

- [ ] **Step 5: Bukti tidak ada sisa instruksi harga lama**

Run: `grep -niE 'reload|\$2\.50|\$5 ?/ ?\$30' docs/LITELLM_IMPLEMENTATION_GUIDE.md`
Expected: tidak ada output.
Run: `make unit`
Expected: lulus.

- [ ] **Step 6: Commit**

```bash
git add docs/LITELLM_IMPLEMENTATION_GUIDE.md
git commit -m "docs: guide plans price governance (pinned prices, provider fuse, monthly reconciliation, drift check)"
```

### Task 4: Fase 4 (otomatisasi rekonsiliasi dan provider kedua)

**Files:**
- Modify: `docs/LITELLM_IMPLEMENTATION_GUIDE.md` (§1 lingkup, §6 timeline dan tabel gate, §6 Fase 4 baru, §8.3, §9, §10)

**Interfaces:**
- Consumes: §3.1 dan runbook 8.7 dari Task 3.

- [ ] **Step 1: §6 Fase 4**

Tambahkan `### Fase 4 — Otomatisasi rekonsiliasi dan provider kedua (setelah go-live)` setelah Fase 3, isinya spec bagian 4.3 sebagai checklist `- [ ]`: subjudul "4a. Otomatisasi rekonsiliasi" (dua item); "4b. Provider kedua" dengan "Syarat masuk" (dua butir, kriteria pemilihan provider ditulis lengkap), checklist enam item, dan "Uji: ulangi T01, T06, T07, T09 (bila ada fallback), T10, dan T11 untuk provider baru".

- [ ] **Step 2: Gate, timeline, lingkup**

- Tabel gate: tambahkan baris `Gate 4 | Uji per provider lulus, sekring provider terpasang, rekonsiliasi berjalan (otomatis atau manual tercatat), runbook 8.3 diperbarui`.
- Di bawah diagram minggu: "Fase 4 tidak dijadwalkan; durasinya ditetapkan setelah provider kedua dipilih."
- §1 kalimat "Di luar lingkup rilis awal: …": tambahkan "Provider kedua direncanakan di Fase 4 (bagian 6)."

- [ ] **Step 3: §8.3, §9, §10**

- §8.3 langkah 3: tambahkan "Setelah Fase 4, pakai fallback lintas provider bila diizinkan untuk alias itu."
- §9 baris "Satu provider (OpenAI)": mitigasi menjadi "Diterima untuk rilis awal; alert dan runbook 8.3; provider kedua di Fase 4".
- §10: tambahkan `- [ ] Provider kedua apa, dan berdasarkan kriteria apa? (lihat Fase 4)`.

- [ ] **Step 4: Verifikasi**

Run: `grep -c 'Fase 4' docs/LITELLM_IMPLEMENTATION_GUIDE.md`
Expected: minimal 6 (judul fase, timeline, §1, §8.3, §9, §10).
Run: `make unit`
Expected: lulus.

- [ ] **Step 5: Commit**

```bash
git add docs/LITELLM_IMPLEMENTATION_GUIDE.md
git commit -m "docs: guide adds Phase 4 for reconciliation automation and a second provider"
```

## Penyelesaian

- [ ] `make unit` lulus di HEAD; `git diff main --stat` hanya berisi spec, plan, guide, `docs/operator-guide.md`, dan `deploy/tests/test_doc_copies.py`.
- [ ] Push ke `origin docs/implementation-guide-sync` (PR #12), perbarui deskripsi PR dengan daftar perubahan, dan tandai *ready for review*.
