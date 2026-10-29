# Implementasi: pilot tanpa Caddy dan TLS

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menghapus Caddy dan TLS dari profil lokal dan VM, sehingga pengguna terhubung langsung ke `litellm-a` lewat HTTP di port `LITELLM_PORT`.

**Architecture:** Service `caddy`, semua Caddyfile, dan semua variabel TLS/host dihapus. Hanya `litellm-a` yang membuka port host: `127.0.0.1` di lokal, semua alamat di VM. Container `tools` memanggil `http://litellm-a:4000`. Uji yang harus mencakup dua replika (T03, T05, offboarding) memanggil kedua replika langsung, karena tidak ada lagi load balancer.

**Tech Stack:** Docker Compose v2, GNU Make, POSIX sh, Python 3.12 dengan pytest, PyYAML, dan httpx (semuanya di container `tools`), LiteLLM v1.106.4 yang dipin ke digest.

**Spec:** `docs/superpowers/specs/2026-10-27-litellm-pilot-design.md`. Perubahannya ada di commit `4abb0e0`: bagian 2, 3, 4.1, 4.2, 8.2 (T10), 10, dan 11.

## Global Constraints

- Port host hanya untuk `litellm-a`: lokal `127.0.0.1:${LITELLM_PORT:-4000}:4000`, VM `${LITELLM_PORT:-4000}:4000`. `litellm-b`, `postgres`, `redis`, `mock-upstream`, dan `tools` tidak punya `ports`.
- `tools`: `LITELLM_BASE_URL` dan `GATEWAY_URL` keduanya bernilai tetap `http://litellm-a:4000` di `deploy/compose.yaml`, tidak diambil dari env.
- Fail-closed tetap berlaku: `LITELLM_LOG: INFO`, tanpa `allow_requests_on_db_unavailable`, tanpa response caching. `deploy/litellm/config.yaml` tidak diubah, kecuali baris komentar. Keputusan pemilik repo 2026-10-30: komentar tentang `read_timeout` Caddy di `litellm_settings` diarahkan ke timeout baca proxy DevOps (spec bagian 10), karena pemeriksaan 4 gerbang sukses menolak kata Caddy di luar `docs`.
- T03 tetap 20 request paralel dengan toleransi overshoot 10%. Ambang ini tidak dilonggarkan, tidak di-skip, dan tidak di-xfail. T09 tidak disentuh.
- Volume Docker yang ada (`*_caddy-data`, `*_caddy-config`, `*_pgdata`) tidak dihapus. Jangan pernah menjalankan `docker compose down -v` pada project `llm-gateway-local` atau `llm-gateway-vm`.
- `docs/*.md` dan pesan untuk operator ditulis dalam bahasa Indonesia; identifier dan komentar kode dalam bahasa Inggris.
- Python hanya berjalan di container `tools` (`make unit`, `docker compose run tools`). Host cukup Docker dan make.
- Isi `deploy/env/*.env`, master key, salt key, password, dan virtual key tidak pernah dicetak atau di-commit.
- Satu commit per task di branch `feat/remove-caddy`, selalu lewat hook pre-commit (tanpa `--no-verify`). Tidak push tanpa izin pemilik repo.
- `make test` tidak boleh berjalan dua kali bersamaan, karena uji acceptance berbagi state stack.
- File yang tidak boleh diubah: spec (sudah final di `4abb0e0`), `docs/LLM_GATEWAY_ARCHITECTURE.md`, `docs/LITELLM_IMPLEMENTATION_GUIDE.md`, `docs/superpowers/plans/2026-10-27-litellm-pilot.md`, `deploy/litellm/config.yaml` (kecuali baris komentar, lihat di atas).

## Review Focus

1. **Upgrade dari stack yang masih punya container `caddy`.** Tanpa `--remove-orphans`, container lama tetap hidup dan memegang port host. Ditangkap oleh `test_up_removes_orphaned_caddy` (Task 2) dan pemeriksaan 7 di gerbang sukses (Task 0b).
2. **`local.env`/`vm.env` lama yang masih berisi variabel yang dihapus** (`VM_TLS`, `LLM_HOST`, `TLS_CERT_DIR`, dan lainnya). Stack harus tetap bisa dirender dan naik. Ditangkap oleh verifikasi `config -q` dengan `vm.env.example` dari `main` (Task 1 Step 6).
3. **Profil lokal tidak sengaja terbuka ke LAN** karena mapping tanpa `127.0.0.1`. Ditangkap oleh `test_only_litellm_a_is_published[compose.local.yaml]` (Task 1).
4. **Edit berikutnya membuka port `litellm-b`, Postgres, atau Redis.** Ditangkap oleh `test_only_litellm_a_is_published` dan `test_base_compose_publishes_nothing` (Task 1).
5. **Operator mengikuti dokumen basi** (`make local-ca`, `https://llm.pilot.test`, `VM_TLS`, `VPN_CIDR`). Ditangkap oleh `deploy/tests/test_docs_access.py` (Task 5 dan 6).

## Struktur file

| File | Aksi | Task |
| --- | --- | --- |
| `.claude/settings.json`, `.claude/hooks/guard-bash.sh`, `.claude/hooks/guard-files.sh`, `deploy/tests/test_claude_hooks.py` | Buat | 0 |
| `.claude/settings.local.json`, `.claude/hooks/remove-caddy-success.sh` | Buat, tidak di-commit (`.git/info/exclude`) | 0b |
| `~/.claude/workflows/remove-caddy.js` | Buat, di luar repo | 0b |
| `deploy/compose.yaml`, `deploy/compose.local.yaml`, `deploy/compose.vm.yaml` | Ubah | 1 |
| `deploy/env/vm.env.example`, `deploy/env/local.env.example`, `scripts/init-local.sh` | Ubah | 1 |
| `deploy/caddy/` (tiga file), `deploy/tests/test_caddy_vm_tls.py`, `deploy/tests/test_caddy_log_redaction.py` | Hapus | 1 |
| `deploy/tests/test_compose_profiles.py` | Buat | 1 |
| `Makefile`, `deploy/tests/test_makefile.py` | Ubah | 2 |
| `tests/helpers.py`, `tests/acceptance/test_budget.py`, `tests/acceptance/test_revocation.py`, `tests/integration/test_gatewayctl.py` | Ubah | 3 |
| `tests/acceptance/test_allowlist.py` | Hapus | 3 |
| `scripts/t10-scan-logs.sh`, `deploy/tests/test_t10_scan.py` | Ubah | 4 |
| `deploy/tests/test_docs_access.py` | Buat (Task 5), tambah parameter (Task 6) | 5, 6 |
| `docs/setup-admin.md` | Ubah | 5 |
| `docs/operator-guide.md`, `docs/pilot-checklist.md`, `docs/onboarding.md`, `docs/opencode.example.json` | Ubah | 6 |
| `deploy/litellm/config.yaml` (baris komentar saja) | Ubah | 7 (perbaikan gerbang) |

Urutan dan ketergantungan antartask ada di bagian [Eksekusi dengan Workflow dan goal](#eksekusi-dengan-workflow-dan-goal).

---

### Task 0: Claude hooks penjaga aturan CLAUDE.md

Workflow dan `/goal` menjalankan banyak langkah tanpa diawasi. Hook `PreToolUse` menolak secara deterministik pelanggaran aturan CLAUDE.md yang paling mahal akibatnya, sebelum perintahnya jalan. Hook ini berlaku untuk sesi utama dan subagent. Keadaan sukses dijaga terpisah oleh Stop hook di Task 0b.

Task 0 dan 0b dikerjakan di sesi utama **sebelum** workflow dijalankan. Hook dibaca saat sesi Claude Code dimulai, jadi run dijalankan di sesi baru.

**Files:**
- Create: `.claude/settings.json`, `.claude/hooks/guard-bash.sh`, `.claude/hooks/guard-files.sh`, `deploy/tests/test_claude_hooks.py`

**Interfaces:**
- Consumes: input hook JSON dari Claude Code di stdin, dengan field `tool_input.command` untuk Bash dan `tool_input.file_path`/`content`/`new_string` untuk Read/Edit/Write.
- Produces:
  - **Tolak:** exit `2`, alasan di stderr dalam bahasa Indonesia.
  - **Minta konfirmasi:** exit `0` dengan JSON `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "..."}}` di stdout.
  - **Izinkan:** exit `0` tanpa keluaran.
  - Skrip hanya memakai POSIX sh, `grep`, dan `sed`, tanpa `jq` atau Python, karena host cukup Docker dan make. Input JSON dicocokkan sebagai teks mentah.

| Skrip | Pola | Keputusan |
| --- | --- | --- |
| `guard-bash.sh` | `down` dengan `-v`/`--volumes`, `docker volume rm`, atau `docker volume prune`, kecuali perintahnya menyebut `llm-gateway-vmverify` atau `llm-gateway-cfgcheck` (project sekali pakai) | tolak |
| `guard-bash.sh` | `git commit` dengan `--no-verify` atau flag `-n` | tolak |
| `guard-bash.sh` | `git push` | minta konfirmasi (CLAUDE.md: tidak push tanpa izin) |
| `guard-bash.sh` | `cat`, `less`, `more`, `head`, `tail`, `grep`, `sed`, `awk`, atau `source` diikuti `deploy/env/<nama>.env` (bukan `.env.example`) di segmen perintah yang sama, tanpa `\|`, `;`, atau `&` di antaranya. `--env-file deploy/env/...` milik `docker compose` tetap boleh. | tolak (isi rahasia tercetak) |
| `guard-bash.sh` | memasang `LITELLM_LOG=DEBUG`: di awal segmen perintah (boleh didahului `export`, `env`, atau assignment lain) atau lewat `-e`/`--env`. Menyebutnya di pesan commit tetap boleh. | tolak |
| `guard-bash.sh` | `make test`, atau `pytest` dengan `tests/acceptance`, saat `pgrep -f 'tests/integration tests/acceptance'` menemukan proses lain | tolak (uji acceptance tidak boleh paralel) |
| `guard-files.sh` | `file_path` berakhiran `deploy/env/<nama>.env` (bukan `.env.example`) | tolak |
| `guard-files.sh` | konten baru berisi `LITELLM_LOG: DEBUG`, `allow_requests_on_db_unavailable: true`, atau `cache: true` di file di bawah `deploy/` | tolak |

- [ ] **Step 1: Tulis test yang gagal di `deploy/tests/test_claude_hooks.py`**

Test menjalankan skrip dengan `subprocess.run(["sh", script], input=json.dumps(payload), capture_output=True, text=True)` di container `tools`. Payload minimal: `{"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": CMD}}`.

```python
DENY_BASH = [
    "docker compose -p llm-gateway-local -f deploy/compose.yaml down -v",
    "docker volume rm llm-gateway-local_pgdata",
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "cat deploy/env/local.env",
    "grep MASTER deploy/env/vm.env",
    "LITELLM_LOG=DEBUG make up",
]
ALLOW_BASH = [
    "docker compose -p llm-gateway-vmverify -f deploy/compose.yaml down -v",
    "make down",
    "git commit -m 'feat: x'",
    "cat deploy/env/vm.env.example",
    "make unit",
    "docker compose --env-file deploy/env/local.env run --rm -T tools pytest -q | grep passed",
]


@pytest.mark.parametrize("cmd", DENY_BASH)
def test_bash_guard_denies(cmd):
    r = _run("guard-bash.sh", {"command": cmd})
    assert r.returncode == 2 and r.stderr.strip()


@pytest.mark.parametrize("cmd", ALLOW_BASH)
def test_bash_guard_allows(cmd):
    r = _run("guard-bash.sh", {"command": cmd})
    assert (r.returncode, r.stdout) == (0, "")


def test_git_push_asks_owner():
    r = _run("guard-bash.sh", {"command": "git push -u origin feat/remove-caddy"})
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"


@pytest.mark.parametrize(
    ("tool_input", "code"),
    [
        ({"file_path": "/x/deploy/env/local.env"}, 2),
        ({"file_path": "/x/deploy/env/vm.env.example"}, 0),
        ({"file_path": "/x/deploy/compose.yaml", "new_string": "  LITELLM_LOG: DEBUG"}, 2),
        ({"file_path": "/x/deploy/litellm/config.yaml", "content": "allow_requests_on_db_unavailable: true"}, 2),
        ({"file_path": "/x/docs/operator-guide.md", "new_string": "Jangan set LITELLM_LOG: DEBUG"}, 0),
    ],
)
def test_file_guard(tool_input, code):
    assert _run("guard-files.sh", tool_input).returncode == code


def test_settings_wire_both_guards():
    settings = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pre = {m["matcher"]: m["hooks"][0]["command"] for m in settings["hooks"]["PreToolUse"]}
    assert pre == {
        "Bash": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard-bash.sh',
        "Read|Edit|Write": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard-files.sh',
    }
    assert "Stop" not in settings["hooks"]  # the success gate is personal (Task 0b)
```

Helper `_run(script: str, tool_input: dict) -> subprocess.CompletedProcess` ada di file test yang sama. `REPO = Path(__file__).resolve().parents[2]`. Kasus antrean `make test` tidak diuji unit, karena butuh proses `pytest` sungguhan; kasus itu diperiksa manual di Step 5.

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `make unit`
Expected: FAIL di semua test `test_claude_hooks.py` dengan `FileNotFoundError` untuk skrip dan `settings.json`.

- [ ] **Step 3: Tulis kedua skrip dan `.claude/settings.json`**

- Skrip dimulai dengan `#!/bin/sh` dan `set -eu`, membaca `input=$(cat)`, lalu mencocokkan `printf '%s' "$input" | grep -Eq '<regex>'` untuk setiap baris tabel di atas.
- Fungsi `deny() { echo "hook: $1" >&2; exit 2; }` dan `ask()` untuk mencetak JSON `ask`.
- Kedua skrip diberi `chmod +x`.

`.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-bash.sh" } ] },
      { "matcher": "Read|Edit|Write", "hooks": [ { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-files.sh" } ] }
    ]
  }
}
```

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `make unit`
Expected: PASS, semua test lulus.

- [ ] **Step 5: Commit**

```bash
git add .claude/settings.json .claude/hooks/guard-bash.sh .claude/hooks/guard-files.sh deploy/tests/test_claude_hooks.py
git commit -m "chore: Claude hooks that block CLAUDE.md violations before they run"
```

---

### Task 0b: Gerbang sukses otomatis (Stop hook, tidak di-commit)

Keadaan sukses dibuktikan oleh mesin, tanpa uji manual. Stop hook ini menjalankan sendiri semua pemeriksaan di bawah setiap kali sesi utama hendak berhenti, dan menahan sesi (exit `2`, alasan dikirim balik ke Claude) sampai semuanya lulus. Gerbang ini hanya untuk run ini, jadi disimpan sebagai file pribadi yang dikecualikan git.

Gerbang tidak melepas blokir saat `stop_hook_active` bernilai true. Selama Claude terus memanggil tool, gerbang tetap menahan. Claude Code sendiri melepas blokir setelah delapan kali lanjut berturut-turut tanpa tool call, sehingga kegagalan yang tidak bisa diperbaiki Claude (misalnya Docker mati) tidak membuat sesi macet selamanya.

**Files** (tidak di-commit):
- `.claude/hooks/remove-caddy-success.sh`, `.claude/settings.local.json`. Keduanya ditambahkan ke `.git/info/exclude`.
- `~/.claude/workflows/remove-caddy.js` (bagian [Eksekusi](#eksekusi-dengan-workflow-dan-goal)).
- Penanda aktif `var/remove-caddy.goal`, serta log dan cache di `var/remove-caddy-success/`. Folder `var/` sudah di-gitignore.

**Interfaces:**
- `remove-caddy-success.sh [--now]`. Input Stop hook JSON dibaca dari stdin bila stdin bukan terminal.
- Sukses: stdout `SUKSES remove-caddy <sha>`, exit `0`.
- Gagal: stderr `GAGAL <nomor> <nama>: <petunjuk> (log: var/remove-caddy-success/<file>)`, exit `2`.
- Skrip tidak pernah mencetak isi env file atau key. Log `make test` hanya berisi nama test dan angka T03/T05/T10.

**Kapan gerbang aktif:**

| Kondisi | Hasil |
| --- | --- |
| Tanpa `--now`, dan `var/remove-caddy.goal` tidak ada atau branch bukan `feat/remove-caddy` | exit `0` seketika (gerbang tidak aktif, sesi lain tidak terganggu) |
| Tanpa `--now`, dan input berisi `background_tasks` yang tidak kosong, atau `pgrep -f 'tests/integration tests/acceptance'` menemukan proses | exit `0` seketika. Workflow masih jalan, dan `make test` tidak boleh berjalan bersamaan. Gerbang dinilai lagi saat sesi berhenti berikutnya. |
| Lainnya, atau `--now` | jalankan pemeriksaan |

**Pemeriksaan**, berurutan dan berhenti di kegagalan pertama (yang murah dulu):

1. Working tree bersih: `git status --porcelain` kosong.
2. Struktur:
   - `deploy/caddy/` dan `tests/acceptance/test_allowlist.py` tidak ada;
   - `deploy/tests/test_compose_profiles.py`, `deploy/tests/test_docs_access.py`, `deploy/tests/test_claude_hooks.py`, `.claude/settings.json`, `.claude/hooks/guard-bash.sh`, dan `.claude/hooks/guard-files.sh` ada.
3. File terlarang tidak berubah:
   - `git diff --quiet main HEAD -- docs/LLM_GATEWAY_ARCHITECTURE.md docs/LITELLM_IMPLEMENTATION_GUIDE.md docs/superpowers/plans/2026-10-27-litellm-pilot.md`;
   - `git diff --quiet -I '^[[:space:]]*#' main HEAD -- deploy/litellm/config.yaml`: hanya baris komentar yang boleh berbeda dari `main`;
   - `git diff --quiet 4abb0e0 HEAD -- docs/superpowers/specs/`.
4. `git grep -n -i caddy -- . ':!docs' ':!deploy/tests' ':!.claude'` tidak mengeluarkan apa-apa. Dokumen dijaga `test_docs_access.py`, dan nama test di `deploy/tests` boleh menyebut Caddy.
5. Cache: bila `var/remove-caddy-success/sha` sama dengan `git rev-parse HEAD`, cetak `SUKSES remove-caddy <sha> (cache)` dan exit `0`.
6. `make unit` lulus (`unit.log`).
7. Stack lokal:
   - `make up` lulus (`up.log`);
   - `docker ps -aq --filter name=llm-gateway-local-caddy` kosong;
   - `docker port llm-gateway-local-litellm-a-1` persis `4000/tcp -> 127.0.0.1:4000`;
   - `docker port llm-gateway-local-litellm-b-1` kosong;
   - `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health/liveliness` mengembalikan `200`.
8. `make test` lulus (`make-test.log`), dan log berisi `T03 spend=`, `T05 revocation seconds=`, serta `sumber: litellm-a litellm-b postgres redis postgres:LiteLLM_SpendLogs)`. Ambangnya sudah dijaga assertion di test.
9. Profil VM di project `llm-gateway-vmverify`, dengan override yang ditulis skrip ke `$(mktemp -d)/override.yaml`:
   - `up -d --wait --wait-timeout 300` lulus;
   - `ps --format '{{.Service}} {{.Ports}}'` hanya menunjukkan port pada `litellm-a` (`127.0.0.1:14000->4000/tcp`);
   - `curl` ke `http://127.0.0.1:14000/health/liveliness` mengembalikan `200`;
   - smoke `4 passed` (`vm-smoke.log`);
   - `down -v` untuk project itu selalu dijalankan lewat `trap`, juga saat gagal, dan tidak pernah menyentuh `llm-gateway-local`.
10. Tulis `HEAD` ke `var/remove-caddy-success/sha`, cetak `SUKSES remove-caddy <sha>`, lalu exit `0`.

Override untuk pemeriksaan 9. Path relatif di override dihitung dari `deploy/`, direktori project:

```yaml
# Verify-only: VM profile against the mock upstream, host port on 127.0.0.1 only.
services:
  mock-upstream:
    image: llm-gateway-mock-upstream
    build: ../mock_upstream
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/v1/models')"]
      interval: 5s
      timeout: 5s
      retries: 12
  litellm-a:
    ports: !override
      - "127.0.0.1:14000:4000"
  tools:
    env_file:
      - path: env/local.env
```

Perintah compose pemeriksaan 9 adalah `docker compose -p llm-gateway-vmverify -f deploy/compose.yaml -f deploy/compose.vm.yaml -f "$override" --env-file deploy/env/local.env ...`. Smoke dijalankan seperti ini; key sekali pakai tidak pernah dicetak:

```sh
run --rm -T -e GATEWAYCTL_OPERATOR=verify@local -e GATEWAYCTL_AUDIT_LOG=/tmp/verify-audit.log tools sh -c '
  gatewayctl --file entitlements/local.yaml apply --confirm >/dev/null 2>&1
  SMOKE_KEY=$(gatewayctl --file entitlements/local.yaml key issue --user dev1@local.test --label verify-vm 2>/dev/null)
  [ -n "$SMOKE_KEY" ] || { echo "key issue gagal" >&2; exit 1; }
  export SMOKE_KEY
  pytest -p no:cacheprovider tests/smoke -q'
```

`.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/remove-caddy-success.sh", "timeout": 2400 } ] }
    ]
  }
}
```

- [ ] **Step 1: Tulis skrip, `settings.local.json`, dan entri exclude**

Skrip memakai POSIX sh dengan `set -u`. Langkah yang dijalankan di dalam skrip memakai `if ! ...; then fail ...; fi`, bukan `set -e`, supaya pesan `GAGAL` selalu tercetak. Lalu:

```bash
chmod +x .claude/hooks/remove-caddy-success.sh
printf '%s\n' .claude/settings.local.json .claude/hooks/remove-caddy-success.sh >> .git/info/exclude
```

- [ ] **Step 2: Pastikan gerbang tidak aktif tanpa penanda**

Run: `printf '{}' | .claude/hooks/remove-caddy-success.sh; echo "exit=$?"`
Expected: `exit=0` tanpa keluaran lain.

- [ ] **Step 3: Pastikan gerbang mengalah saat workflow berjalan**

Run: `mkdir -p var && touch var/remove-caddy.goal && printf '{"background_tasks":[{"type":"workflow"}]}' | .claude/hooks/remove-caddy-success.sh; echo "exit=$?"; rm var/remove-caddy.goal`
Expected: `exit=0`, tanpa menjalankan `make`.

- [ ] **Step 4: Pastikan gerbang menolak sebelum Task 1–6 selesai**

Run: `.claude/hooks/remove-caddy-success.sh --now; echo "exit=$?"`
Expected: `GAGAL 2 struktur: deploy/caddy/ masih ada ...` dan `exit=2`. Working tree bersih karena file lokal dikecualikan, jadi pemeriksaan 1 lulus.

- [ ] **Step 5: Pastikan tidak ada file lokal yang ikut ter-commit**

Run: `git status --porcelain`
Expected: kosong.

---

### Task 1: Compose dan env tanpa Caddy

**Files:**
- Create: `deploy/tests/test_compose_profiles.py`
- Modify: `deploy/compose.yaml`, `deploy/compose.local.yaml`, `deploy/compose.vm.yaml`, `deploy/env/vm.env.example`, `deploy/env/local.env.example`, `scripts/init-local.sh`
- Delete: `deploy/caddy/Caddyfile.local`, `deploy/caddy/Caddyfile.vm`, `deploy/caddy/common.caddy`, `deploy/tests/test_caddy_vm_tls.py`, `deploy/tests/test_caddy_log_redaction.py`

**Interfaces:**
- Consumes: tidak ada.
- Produces: env `LITELLM_PORT` (default 4000) untuk port host `litellm-a`. Di container `tools`, `GATEWAY_URL=http://litellm-a:4000`. Task 3 dan Task 7 memakai keduanya.

- [ ] **Step 1: Tulis test yang gagal di `deploy/tests/test_compose_profiles.py`**

```python
"""Static checks on the compose profiles: no reverse proxy, only litellm-a is published (spec 4.1, 4.2, 10)."""

import re
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[1]
REPO = DEPLOY.parent
COMPOSE_FILES = ["compose.yaml", "compose.local.yaml", "compose.vm.yaml"]
# Variables that only Caddy and TLS used; old env files may still carry them.
REMOVED_VARS = ["VM_TLS", "LLM_HOST", "LLM_ADMIN_HOST", "LLM_HTTP_PORT", "LLM_HTTPS_PORT",
                "TLS_CERT_DIR", "VPN_CIDR", "GATEWAY_CA_BUNDLE"]


def _compose(name: str) -> dict:
    return yaml.safe_load((DEPLOY / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_no_caddy_service(name):
    assert "caddy" not in _compose(name)["services"]


def test_caddy_config_and_volumes_are_gone():
    assert not (DEPLOY / "caddy").exists()
    assert set(_compose("compose.yaml")["volumes"]) == {"pgdata"}


def test_base_compose_publishes_nothing():
    assert [s for s, d in _compose("compose.yaml")["services"].items() if "ports" in d] == []


@pytest.mark.parametrize(
    ("name", "ports"),
    [
        ("compose.local.yaml", ["127.0.0.1:${LITELLM_PORT:-4000}:4000"]),
        ("compose.vm.yaml", ["${LITELLM_PORT:-4000}:4000"]),
    ],
)
def test_only_litellm_a_is_published(name, ports):
    services = _compose(name)["services"]
    assert [s for s, d in services.items() if "ports" in d] == ["litellm-a"]
    assert services["litellm-a"]["ports"] == ports


def test_tools_reaches_litellm_a_inside_compose_network():
    env = _compose("compose.yaml")["services"]["tools"]["environment"]
    assert env["LITELLM_BASE_URL"] == "http://litellm-a:4000"
    assert env["GATEWAY_URL"] == "http://litellm-a:4000"
    for name in ("compose.local.yaml", "compose.vm.yaml"):
        overlay = _compose(name)["services"]["tools"].get("environment", {})
        assert "GATEWAY_URL" not in overlay and "GATEWAY_CA_BUNDLE" not in overlay


@pytest.mark.parametrize(
    "path",
    ["deploy/compose.yaml", "deploy/compose.local.yaml", "deploy/compose.vm.yaml",
     "deploy/env/vm.env.example", "deploy/env/local.env.example", "scripts/init-local.sh"],
)
def test_removed_variables_are_gone(path):
    text = (REPO / path).read_text(encoding="utf-8")
    assert [v for v in REMOVED_VARS if re.search(rf"\b{v}\b", text)] == []


def test_vm_env_example_sets_litellm_port():
    text = (DEPLOY / "env" / "vm.env.example").read_text(encoding="utf-8")
    assert re.search(r"^LITELLM_PORT=4000$", text, re.M)
```

- [ ] **Step 2: Jalankan `make unit` dan pastikan test baru gagal**

Run: `make unit`
Expected: FAIL. Gagal karena Caddy masih ada, bukan karena salah ketik atau `ImportError`. Yang harus gagal:
- `test_no_caddy_service[...]` (tiga parameter)
- `test_caddy_config_and_volumes_are_gone`
- `test_only_litellm_a_is_published[...]` (dua parameter)
- `test_tools_reaches_litellm_a_inside_compose_network`
- `test_removed_variables_are_gone[...]` (enam parameter)
- `test_vm_env_example_sets_litellm_port`

- [ ] **Step 3: Hapus Caddy dan test-nya**

```bash
git rm -q deploy/caddy/Caddyfile.local deploy/caddy/Caddyfile.vm deploy/caddy/common.caddy \
  deploy/tests/test_caddy_vm_tls.py deploy/tests/test_caddy_log_redaction.py
```

- [ ] **Step 4: Ubah file Compose, env, dan `init-local.sh`**

`deploy/compose.yaml`:
- Hapus seluruh blok service `caddy` dan volume `caddy-data` serta `caddy-config`, sehingga `volumes:` hanya berisi `pgdata:`.
- Ubah env `tools` menjadi:

```yaml
    environment:
      LITELLM_BASE_URL: http://litellm-a:4000
      # Users reach litellm-a directly (spec 4.2); tests take the same path.
      GATEWAY_URL: http://litellm-a:4000
```

`deploy/compose.local.yaml`, isi lengkap. Blok `mock-upstream` disalin persis dari versi sekarang:

```yaml
# Local profile: mock upstream instead of OpenAI; litellm-a published on
# 127.0.0.1 only.

services:
  mock-upstream:
    # (salin blok mock-upstream yang sekarang apa adanya: image, build, healthcheck, restart)

  litellm-a:
    ports:
      - "127.0.0.1:${LITELLM_PORT:-4000}:4000"

  tools:
    env_file:
      - path: env/local.env
        required: false
    environment:
      MOCK_URL: http://mock-upstream:8080
```

`deploy/compose.vm.yaml`, isi lengkap:

```yaml
# VM profile: real OpenAI upstream. Users reach litellm-a directly over HTTP;
# TLS and the network edge belong to DevOps (spec section 10).

services:
  litellm-a:
    ports:
      - "${LITELLM_PORT:-4000}:4000"

  tools:
    env_file:
      - path: env/vm.env
        required: false
```

`deploy/env/vm.env.example`: ganti semua baris dari `# Sertifikat TLS: ...` sampai `TLS_CERT_DIR=...` dengan:

```sh
# Port litellm-a di host; pengguna memakai http://<ip-vm>:<port>/v1. Tanpa TLS:
# virtual key dan master key lewat jaringan kantor tanpa enkripsi sampai proxy
# DevOps dipasang (spec bagian 10). Ganti bila port 4000 sudah dipakai.
LITELLM_PORT=4000
```

`deploy/env/local.env.example` dan `scripts/init-local.sh`: hapus baris `LLM_HOST=...` dan `LLM_ADMIN_HOST=...` (di `init-local.sh`, dua baris `echo`).

- [ ] **Step 5: Jalankan `make unit` dan pastikan semua test lulus**

Run: `make unit`
Expected: PASS, semua test lulus. Satu-satunya peringatan yang boleh muncul adalah deprecation dari `fastapi.testclient` yang sudah ada sebelumnya.

- [ ] **Step 6: Pastikan Compose bisa dirender, termasuk dengan env lama**

```bash
tmp=$(mktemp -d)
git show main:deploy/env/vm.env.example > "$tmp/legacy-vm.env"
for env in deploy/env/vm.env.example "$tmp/legacy-vm.env"; do
  docker compose -p llm-gateway-cfgcheck --profile tools -f deploy/compose.yaml -f deploy/compose.vm.yaml \
    --env-file "$env" config -q && echo "OK $env"
done
make config && echo "OK local"
rm -rf "$tmp"
```

Expected: tiga baris `OK`, tanpa error `belum diisi` dan tanpa isi config tercetak. `make config` memakai `deploy/env/local.env` milik operator, yang masih berisi `LLM_HOST`. Ini membuktikan Review Focus 2.

- [ ] **Step 7: Commit**

```bash
git add -A deploy/compose.yaml deploy/compose.local.yaml deploy/compose.vm.yaml deploy/env/vm.env.example \
  deploy/env/local.env.example scripts/init-local.sh deploy/tests/test_compose_profiles.py
git commit -m "feat: drop Caddy; publish litellm-a only (LITELLM_PORT)"
```

---

### Task 2: Makefile tanpa target CA Caddy

**Files:**
- Modify: `Makefile`, `deploy/tests/test_makefile.py`

**Interfaces:**
- Consumes: Task 1 (`deploy/caddy/` sudah tidak ada).
- Produces: `make up` membuang container yatim (orphan). `make test` cukup bergantung pada `unit`, dan `make smoke` tanpa prasyarat.

- [ ] **Step 1: Ubah `deploy/tests/test_makefile.py`**

- Hapus `test_vm_ca_copies_caddy_root_for_vm_only`.
- Tambahkan `import re` dan tiga test berikut:

```python
def test_caddy_ca_targets_are_gone():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert not re.search(r"^(local|vm)-ca:", text, re.M)
    assert "caddy" not in text.lower()


def test_test_and_smoke_need_no_ca():
    assert _prerequisites("test") == ["unit"]
    assert _prerequisites("smoke") == []


def test_up_removes_orphaned_caddy():
    # A stack started before this change still has a caddy container holding host ports.
    assert "--remove-orphans" in " ".join(_recipe("up"))
```

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `make unit`
Expected: FAIL pada tiga test baru di atas. Test lain lulus.

- [ ] **Step 3: Ubah `Makefile`**

- `.PHONY`: hapus `local-ca` dan `vm-ca`.
- Hapus blok `LOCAL_CA := ...`/`local-ca:` dan `VM_CA := ...`/`vm-ca:`, termasuk komentar di atas masing-masing.
- Ubah `test: unit local-ca` menjadi `test: unit`, dan `smoke: local-ca` menjadi `smoke:`.
- Ubah recipe `up` menjadi `$(COMPOSE) up -d --build --wait --wait-timeout 300 --remove-orphans`, dengan komentar di atasnya: `# --remove-orphans: drops containers of services no longer in the compose files (the old reverse proxy).` Kata `caddy` tidak boleh muncul di Makefile.

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `make unit`
Expected: PASS, semua test lulus.

- [ ] **Step 5: Commit**

```bash
git add Makefile deploy/tests/test_makefile.py
git commit -m "build: drop Caddy CA targets; make up removes orphaned containers"
```

---

### Task 3: Uji dua replika tanpa load balancer

**Files:**
- Modify: `tests/helpers.py`, `tests/acceptance/test_budget.py`, `tests/acceptance/test_revocation.py`, `tests/integration/test_gatewayctl.py`
- Delete: `tests/acceptance/test_allowlist.py`

**Interfaces:**
- Consumes: Task 1 (`GATEWAY_URL=http://litellm-a:4000`) dan Task 2 (`make up --remove-orphans`).
- Produces: `helpers.REPLICAS: tuple[str, str] = ("litellm-a", "litellm-b")`. `helpers.gateway(key: str) -> httpx.Client` tanpa CA bundle.

Task ini tidak punya langkah "test gagal dulu", karena yang diubah adalah test itu sendiri. Sebelum perubahan pun, T03 dan offboarding tetap lulus terhadap stack tanpa Caddy. Hanya saja keduanya diam-diam cuma mengenai `litellm-a`, dan itulah yang diperbaiki. `test_allowlist.py` gagal terhadap stack tanpa Caddy (TLS ke port HTTP), sehingga dihapus.

- [ ] **Step 1: Ubah `tests/helpers.py`**

- Hapus `_verify()` dan import `ssl`.
- `gateway()` memanggil `httpx.Client(base_url=_env("GATEWAY_URL"), headers=_auth(key), timeout=TIMEOUT)`, dengan docstring `"""Client for the address users reach: litellm-a directly (spec 4.2). httpx never retries by itself."""`.
- Tambahkan konstanta modul `REPLICAS = ("litellm-a", "litellm-b")` di dekat `TIMEOUT`.

- [ ] **Step 2: T03 menyebar sendiri ke kedua replika (`tests/acceptance/test_budget.py`)**

Ganti `with gateway(key) as client, ThreadPoolExecutor(...)` di `test_t03_parallel_overshoot_within_tolerance` dengan pola berikut. Nilai `T03_PARALLEL`, `T03_TOLERANCE`, dan semua assertion tidak berubah.

```python
    # Spread evenly over both replicas (spec 8.2): without a load balancer the
    # test does it, so the budget counter is still shared across two processes.
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=T03_PARALLEL) as pool:
        clients = [stack.enter_context(replica(name, key)) for name in REPLICAS]
        responses = list(pool.map(lambda i: chat(clients[i % len(clients)], "company-fast"), range(T03_PARALLEL)))
```

Import `ExitStack` dari `contextlib`, serta `REPLICAS` dan `replica` dari `helpers`. Import `gateway` tetap, karena `test_t02` masih memakainya.

- [ ] **Step 3: T05 memakai konstanta bersama (`tests/acceptance/test_revocation.py`)**

Hapus konstanta lokal `REPLICAS` dan import `REPLICAS` dari `helpers`. Perilaku tidak berubah.

- [ ] **Step 4: Offboarding memeriksa kedua replika (`tests/integration/test_gatewayctl.py`)**

- Ganti `_wait_for_status(key: str, status: int) -> int` dengan `_wait_for_status(key: str, status: int) -> dict[str, int]`.
  - Fungsi baru membuka `replica(name, key)` untuk setiap `name` di `REPLICAS`, lalu setiap `POLL_INTERVAL_S` memanggil `chat(client, "company-fast")` di semua replika.
  - Fungsi kembali begitu semua replika mengembalikan `status`, atau saat `REVOCATION_TIMEOUT_S` habis, dengan nilai `{name: status_code_terakhir}`.
  - Docstring: `"""Poll every replica directly until all of them return `status` (no load balancer in front)."""`
- Pemanggilnya menjadi `assert _wait_for_status(key, 401) == {name: 401 for name in REPLICAS}`.
- Import `REPLICAS` dan `replica` dari `helpers`.

- [ ] **Step 5: Hapus uji allowlist**

```bash
git rm -q tests/acceptance/test_allowlist.py
```

- [ ] **Step 6: Jalankan unit, lalu uji yang terdampak terhadap stack lokal**

```bash
make unit
make up
docker compose -p llm-gateway-local -f deploy/compose.yaml -f deploy/compose.local.yaml --env-file deploy/env/local.env \
  run --rm -T tools pytest -p no:cacheprovider tests/acceptance/test_budget.py tests/acceptance/test_revocation.py \
  tests/integration/test_gatewayctl.py tests/acceptance/test_access.py -v
```

Expected:
- `make unit` PASS.
- `make up` membuang `llm-gateway-local-caddy-1` (keluaran berisi `Removing orphan container`).
- Semua test yang dipilih `PASSED`. Baris `T03 spend=... overshoot=...` tercetak dengan `overshoot` ≤ 10%.

Jangan jalankan perintah ini bersamaan dengan `make test`.

- [ ] **Step 7: Commit**

```bash
git add -A tests/helpers.py tests/acceptance tests/integration/test_gatewayctl.py
git commit -m "test: spread T03 and offboarding over both replicas; drop allowlist test"
```

---

### Task 4: Pemindai T10 tanpa log Caddy

**Files:**
- Modify: `scripts/t10-scan-logs.sh`, `deploy/tests/test_t10_scan.py`

**Interfaces:**
- Consumes: tidak ada.
- Produces: baris sukses `T10 clean (<n> nilai, sumber: litellm-a litellm-b postgres redis postgres:LiteLLM_SpendLogs)`.

- [ ] **Step 1: Ubah `deploy/tests/test_t10_scan.py` dulu**

- `SERVICES = ["litellm-a", "litellm-b", "postgres", "redis"]`.
- Di fixture `repo`: hapus baris `(stub / "logs-caddy").write_text(...)`, dan hapus `LLM_HOST=llm.pilot.test\n` dari isi `local.env`.
- Di parametrize `test_leak_names_source_without_value`: hapus `("logs-caddy", PROMPT, "caddy")`.
- Hapus `test_caddy_access_log_without_inference_request_fails`.
- Tambahkan dua test:

```python
def test_clean_result_names_sources(repo):
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "sumber: litellm-a litellm-b postgres redis postgres:LiteLLM_SpendLogs)" in result.stdout


def test_caddy_logs_are_not_scanned(repo):
    # Caddy is gone (spec 10); a leftover container's log is not a gateway source.
    (repo / "stub" / "logs-caddy").write_text(f"caddy-1  | {PROMPT}\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `make unit`
Expected: FAIL. `test_clean_logs`, `test_clean_result_names_sources`, `test_caddy_logs_are_not_scanned`, dan test lain di file itu gagal dengan pesan `access log Caddy tidak berisi request`, karena skrip masih memindai `caddy`.

- [ ] **Step 3: Ubah `scripts/t10-scan-logs.sh`**

- `SERVICES="litellm-a litellm-b postgres redis"`.
- Hapus blok `if [ "$svc" = caddy ] ...; then fail ...; fi` di dalam loop.
- Komentar kepala: ganti "the spend log and the Caddy access log" dengan "the spend log".

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `make unit`
Expected: PASS, semua test lulus.

- [ ] **Step 5: Commit**

```bash
git add scripts/t10-scan-logs.sh deploy/tests/test_t10_scan.py
git commit -m "test: T10 scans gateway containers and spend log, no Caddy access log"
```

---

### Task 5: `docs/setup-admin.md` tanpa Caddy

**Files:**
- Create: `deploy/tests/test_docs_access.py`
- Modify: `docs/setup-admin.md`

**Interfaces:**
- Consumes: nama variabel dan port dari Task 1, target Makefile dari Task 2.
- Produces: `deploy/tests/test_docs_access.py`, dengan dict `DOCS: dict[str, list[str]]` (path → potongan teks yang wajib ada). Task 6 menambah entri ke dict ini.

- [ ] **Step 1: Tulis test dokumen**

```python
"""Operator and user docs describe the gateway without Caddy or TLS (spec 4.2, 10)."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# Instructions that no longer work. Case-insensitive.
STALE = [
    "make local-ca", "make vm-ca", "-f caddy", "caddy-local-root", "caddy-vm-root", "VM_TLS", "LLM_HOST", "LLM_ADMIN_HOST", "LLM_HTTP_PORT",
    "LLM_HTTPS_PORT", "VPN_CIDR", "TLS_CERT_DIR", "GATEWAY_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    "llm.pilot.test", "--resolve", "--cacert", "https://llm", "https://10.", "https://<ip",
]
# Path -> text that must appear.
DOCS = {
    "docs/setup-admin.md": ["LITELLM_PORT", "http://127.0.0.1:4000", "http://10.0.0.5:4000/v1"],
}


@pytest.mark.parametrize("path", sorted(DOCS))
def test_no_stale_instructions(path):
    text = (REPO / path).read_text(encoding="utf-8").lower()
    assert [s for s in STALE if s.lower() in text] == []


@pytest.mark.parametrize("path", sorted(DOCS))
def test_required_facts(path):
    text = (REPO / path).read_text(encoding="utf-8")
    assert [s for s in DOCS[path] if s not in text] == []
```

`re` hanya perlu diimpor bila dipakai; hapus kalau tidak.

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `make unit`
Expected: FAIL pada `test_no_stale_instructions[docs/setup-admin.md]` (misalnya `make local-ca`, `VM_TLS`, `--resolve`) dan `test_required_facts[docs/setup-admin.md]`.

- [ ] **Step 3: Tulis ulang bagian yang terdampak di `docs/setup-admin.md`**

Fakta wajib per bagian:

| Bagian | Isi baru |
| --- | --- |
| A4 | `make ps`: lima service, semuanya `Up ... (healthy)`: `litellm-a`, `litellm-b`, `mock-upstream`, `postgres`, `redis`. Baris `caddy` dihapus. |
| A6 | Tanpa `make local-ca`. `curl -sS http://127.0.0.1:4000/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d '{"model":"company-coding","messages":[{"role":"user","content":"halo"}]}'`. Hasil yang diharapkan tetap `mock-ok`. |
| Pembuka Bagian B | Tabel tiga mode diganti: alamat pengguna `http://10.0.0.5:4000/v1`, Admin UI `http://10.0.0.5:4000/ui` (login master key). Kotak peringatan: tanpa enkripsi, tanpa allowlist path, management API dan Admin UI terbuka ke jaringan kantor dengan master key sebagai satu-satunya pelindung. Hanya untuk jaringan kantor sampai proxy DevOps dipasang (spec bagian 10). |
| B1 | Butir VPN dihapus. Port `LITELLM_PORT` (default 4000) terbuka dari jaringan kantor dan belum dipakai: `sudo ss -ltnp \| grep ':4000 '` harus kosong; kalau ada isinya, pilih port lain di B3. |
| B3 | Baris `VM_TLS`, `LLM_HOST`, `LLM_ADMIN_HOST`, `LLM_HTTP_PORT`, `LLM_HTTPS_PORT`, `VPN_CIDR`, dan `TLS_CERT_DIR` diganti satu baris `LITELLM_PORT`: biarkan `4000`, ganti bila port itu terpakai. Blok "Tambahkan juga satu baris..." dihapus. |
| B4 | Judul baru "Bila VM pernah dipasang dengan versi lama (dengan Caddy)". Di `vm.env` cukup ada rahasia (`LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_API_BASE`) dan `LITELLM_PORT`. Baris lain boleh dihapus dan tidak mengganggu bila tertinggal. Nama variabel lama tidak ditulis, karena `STALE` menolaknya. Lalu `make up ENV=vm`, yang membuang container Caddy lama otomatis. Volume lama dibiarkan. |
| B5 | `make up ENV=vm`, `make ps ENV=vm` (empat service healthy, tanpa `mock-upstream`). Dari laptop: `curl -sS http://10.0.0.5:4000/health/liveliness` → `200`/`"I'm alive!"`; `curl -sS -o /dev/null -w '%{http_code}\n' http://10.0.0.5:4000/key/list` → `401` (management API butuh master key). Kalau gagal: `address already in use` → ganti `LITELLM_PORT`; `Connection refused`/timeout → firewall VM belum membuka port, atau laptop tidak di jaringan kantor. |
| B7 | Tanpa langkah CA. Salin template seperti di `docs/onboarding.md`, `baseURL` `http://10.0.0.5:4000/v1`, simpan key sebagai `COMPANY_LLM_KEY`. |
| "Nanti: ..." | Judul "Nanti: proxy DevOps di depan VM". Daftar kebutuhan dari spec bagian 10 (TLS, allowlist tiga path, management API dan Admin UI hanya dari jaringan tepercaya, load balancing ke kedua replika dengan port `litellm-b` dibuka lewat perubahan repo, timeout baca ≥ 600 detik tanpa buffering, header key tidak dicatat di access log). Setelah siap, pengguna mengganti `baseURL` ke alamat proxy. |
| C "Melihat log" | `make logs ARGS='-f litellm-a'` menggantikan baris `caddy`. |

Ganti `10.0.0.5` dengan IP VM di semua contoh, sama seperti sekarang.

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `make unit`
Expected: PASS, semua test lulus.

- [ ] **Step 5: Commit**

```bash
git add docs/setup-admin.md deploy/tests/test_docs_access.py
git commit -m "docs: admin setup without Caddy or TLS (LITELLM_PORT)"
```

---

### Task 6: Dokumen operator dan pengguna lainnya

**Files:**
- Modify: `docs/operator-guide.md`, `docs/pilot-checklist.md`, `docs/onboarding.md`, `docs/opencode.example.json`, `deploy/tests/test_docs_access.py`

**Interfaces:**
- Consumes: `DOCS` dari Task 5.
- Produces: tidak ada.

- [ ] **Step 1: Tambah entri ke `DOCS` di `deploy/tests/test_docs_access.py`**

```python
    "docs/operator-guide.md": ["LITELLM_PORT", "http://127.0.0.1:4000", "--remove-orphans"],
    "docs/pilot-checklist.md": ["LITELLM_PORT", "http://<ip-vm>:<LITELLM_PORT>/v1"],
    "docs/onboarding.md": ["http://10.0.0.5:4000/v1"],
    "docs/opencode.example.json": ['"baseURL": "http://<ip-vm>:4000/v1"'],
```

Tambahkan juga test berikut, supaya template tetap JSON valid:

```python
def test_opencode_template_is_valid_json():
    import json
    doc = json.loads((REPO / "docs" / "opencode.example.json").read_text(encoding="utf-8"))
    assert doc["provider"]["company"]["options"]["baseURL"] == "http://<ip-vm>:4000/v1"
```

- [ ] **Step 2: Jalankan test dan pastikan gagal**

Run: `make unit`
Expected: FAIL pada parameter keempat dokumen baru dan pada `test_opencode_template_is_valid_json`. `test_makefile.py::test_smoke_key_is_not_documented_as_make_argument` tetap lulus.

- [ ] **Step 3: Ubah dokumen**

| File | Isi baru |
| --- | --- |
| `docs/operator-guide.md` §1 | Diagram: `client (OpenCode/curl) --HTTP--> litellm-a (port LITELLM_PORT; litellm-b hanya di jaringan Docker) --> OpenAI (VM) atau mock-upstream (lokal)`, lalu Postgres dan Redis seperti sekarang. Hapus baris host inference dan host admin. |
| `docs/operator-guide.md` tabel profil | Baris Alamat: lokal `http://127.0.0.1:4000`, VM `http://<ip-vm>:4000` (`LITELLM_PORT`). Baris TLS: "tidak ada; TLS diurus DevOps di level jaringan (spec bagian 10)". Baris Host admin diganti "Admin UI dan management API": "port yang sama (`/ui`), dilindungi master key; lokal hanya dari `127.0.0.1`". |
| `docs/operator-guide.md` §3 | Tanpa `make local-ca`. `curl -sS http://127.0.0.1:4000/v1/chat/completions ...`. OpenCode lokal: `baseURL` `http://127.0.0.1:4000/v1`, tanpa `/etc/hosts` dan tanpa CA. |
| `docs/operator-guide.md` §4 log | `make logs ARGS='-f litellm-a'` menggantikan baris `caddy`. |
| `docs/operator-guide.md` §6 | Hapus butir Sertifikat dan DNS. Butir Jaringan: port `LITELLM_PORT` terbuka dari jaringan kantor, VM bisa keluar ke `api.openai.com`. Cek: `curl -sS http://<ip-vm>:4000/health/liveliness` → 200. |
| `docs/operator-guide.md` §7 | Baris `bind: address already in use` → ganti `LITELLM_PORT`. Hapus baris sertifikat lokal, 404 host inference, 403 host admin, dan error sertifikat VM. Baris baru: "Port lama (8443, 80, 443) masih dipakai container gateway setelah update" → `make up` (atau `make up ENV=vm`) memakai `--remove-orphans` untuk membuang container lama. |
| `docs/pilot-checklist.md` | Gate 1: baris "Domain internal" dan "CIDR VPN" diganti "Akses jaringan dan TLS" dengan nilai sementara "HTTP langsung ke `litellm-a` di `LITELLM_PORT`; TLS dan proxy oleh DevOps (spec bagian 10)". Langkah 2.1: hapus `VPN_CIDR` dari daftar isian. Langkah 2.2 diganti: isi `LITELLM_PORT` (default 4000), pastikan port itu terbuka dari jaringan kantor. Langkah 2.3: hapus `make vm-ca`. Bagian 4: `baseURL` `http://<ip-vm>:<LITELLM_PORT>/v1`, tanpa CA. Baris `SMOKE_KEY="$SMOKE_KEY" make smoke ENV=vm` tetap ada. |
| `docs/onboarding.md` §2 | Dua paragraf IP/CA diganti: tim platform memberi alamat gateway, misalnya `http://10.0.0.5:4000/v1`; ganti `baseURL` dengan alamat itu. Pakai hanya di jaringan kantor, karena key terkirim tanpa enkripsi. |
| `docs/opencode.example.json` | `"baseURL": "http://<ip-vm>:4000/v1"`. Isi lain tidak berubah. |

- [ ] **Step 4: Jalankan test dan pastikan lulus**

Run: `make unit`
Expected: PASS, semua test lulus.

- [ ] **Step 5: Commit**

```bash
git add docs/operator-guide.md docs/pilot-checklist.md docs/onboarding.md docs/opencode.example.json deploy/tests/test_docs_access.py
git commit -m "docs: operator, checklist and onboarding without Caddy or TLS"
```

---

### Task 7: Verifikasi menyeluruh dan PR

**Files:** tidak ada perubahan kode.

**Interfaces:**
- Consumes: semua task sebelumnya.
- Produces: bukti untuk deskripsi PR.

- [ ] **Step 1: Jalankan gerbang sukses**

Run: `.claude/hooks/remove-caddy-success.sh --now; echo "exit=$?"`. Pemeriksaan ini bisa lebih dari 10 menit, jadi jalankan di latar belakang (opsi `run_in_background` pada tool Bash), tunggu sampai selesai, lalu baca `var/remove-caddy-success/result`.
Expected: `SUKSES remove-caddy <sha>` dan `exit=0`. Keluaran ini juga menjadi bukti bagi `/goal`. Angka T03, T05, dan T10 untuk PR diambil dari `var/remove-caddy-success/make-test.log`, dan hasil smoke VM dari `vm-smoke.log`.

- [ ] **Step 2: Minta izin push, lalu buat PR**

Tanyakan dulu ke pemilik repo. Setelah diizinkan:

```bash
git push -u origin feat/remove-caddy
gh pr create --base main --head feat/remove-caddy --title "feat: pilot without Caddy or TLS; users reach litellm-a directly" --body-file <file di scratchpad>
```

Deskripsi PR memuat:
- ringkasan keputusan (spec bagian 10);
- daftar kontrol yang ditanggalkan;
- migrasi untuk lokal dan VM;
- hasil gerbang sukses dengan angka T03, T05, T10, dan smoke VM;
- bagian "Belum diuji": VM sungguhan, OpenCode ke `http://<ip-vm>:4000/v1`, serta smoke T06, T07, dan T11 ke OpenAI asli.

Akhiri deskripsi dengan baris atribusi sesi.

---

## Eksekusi dengan Workflow dan goal

### Urutan dan ketergantungan

```
Task 0, Task 0b (sesi persiapan)
  └─ sesi baru: /goal + "touch var/remove-caddy.goal, lalu jalankan workflow remove-caddy"
       └─> workflow: Task 1 ─> 2 ─> 3 ─> 4 ─> 5 ─> 6 (masing-masing: implementer → reviewer) ─> Task 7 Step 1
            └─> sesi utama berhenti → Stop hook gerbang sukses → lulus, atau Claude lanjut memperbaiki
                 └─> Task 7 Step 2 (izin push dan PR dari pemilik repo; di luar keadaan sukses)
```

Task 1–6 dijalankan berurutan di satu working tree, bukan paralel:
- Setiap task menjalankan `make unit` atas seluruh suite, sehingga test RED milik task lain akan membuatnya gagal.
- Task 3, Task 7, dan gerbang sukses memakai stack lokal yang sama, dan `make test` tidak boleh berjalan bersamaan. Karena itu gerbang mengalah selama workflow masih berjalan.

Paralelisme workflow dipakai untuk review: setiap task diperiksa reviewer independen sebelum task berikutnya mulai.

### Saved workflow `remove-caddy`

File: `~/.claude/workflows/remove-caddy.js`. Ini workflow pribadi, tidak di-commit, karena hanya dipakai sekali. File ini dibuat di Task 0b. Isinya:

```js
export const meta = {
  name: 'remove-caddy',
  description: 'Execute docs/superpowers/plans/2026-10-29-remove-caddy.md Tasks 1-7 Step 1 on feat/remove-caddy (no push)',
  whenToUse: 'Only in company-ai-platform on branch feat/remove-caddy, after plan Task 0 and 0b are done.',
  phases: [
    { title: 'Implement', detail: 'one fresh agent per task, plan steps in order' },
    { title: 'Review', detail: 'independent reviewer per task; up to 3 rounds' },
    { title: 'Verify', detail: 'success gate .claude/hooks/remove-caddy-success.sh --now' },
  ],
}

const PLAN = 'docs/superpowers/plans/2026-10-29-remove-caddy.md'
const GATE = '.claude/hooks/remove-caddy-success.sh'
const RULES =
  `Work in the current checkout on branch feat/remove-caddy. Read the plan's Global Constraints first. ` +
  `Never push, never open a PR, never amend or rebase. Never edit ${GATE}, .claude/settings.local.json or the ` +
  `spec. Commands that can run longer than 10 minutes (make test, the success gate) go through the Bash tool's ` +
  `run_in_background option; wait for them to finish. No other make test may run at the same time.`
const VERDICT = {
  type: 'object',
  required: ['approved', 'issues'],
  properties: {
    approved: { type: 'boolean' },
    issues: { type: 'array', items: { type: 'string' } },
  },
}

for (const n of [1, 2, 3, 4, 5, 6]) {
  let feedback = ''
  for (let round = 0; round < 3; round++) {
    await agent(
      `Implement Task ${n} of ${PLAN} exactly, step by step, including its failing-test step and its commit. ` +
        `${RULES} ${feedback}`,
      { label: round ? `task-${n}-fix${round}` : `task-${n}`, phase: 'Implement' },
    )
    const v = await agent(
      `Review Task ${n} of ${PLAN} as committed on feat/remove-caddy (git log --oneline main..HEAD, git show). ` +
        `Check it against the task's steps, the plan's Global Constraints and the spec (commit 4abb0e0). ` +
        `Run every verification the task names yourself (at least make unit). Approve only if every expected ` +
        `result holds and nothing outside the task's Files changed. List concrete issues otherwise. ${RULES}`,
      { label: `review-${n}`, phase: 'Review', schema: VERDICT },
    )
    if (v && v.approved) break
    const issues = v ? v.issues.join('; ') : 'reviewer returned nothing'
    if (round === 2) throw new Error(`Task ${n} not approved after 3 rounds: ${issues}`)
    feedback = `A reviewer rejected the previous attempt. Fix these in a new commit: ${issues}`
  }
  log(`Task ${n} approved`)
}

phase('Verify')
return await agent(
  `Run Task 7 Step 1 of ${PLAN}: ${GATE} --now, in the background, then read var/remove-caddy-success/result. ` +
    `If it starts with GAGAL, read the named log, fix the cause in a new commit that follows the plan, and run ` +
    `the gate again, at most 3 times. If the gate itself looks wrong, stop and say why instead of working ` +
    `around it. Return the final result line verbatim, then git log --oneline main..HEAD. ${RULES}`,
  { label: 'verify', phase: 'Verify' },
)
```

### Memulai run (satu-satunya langkah manusia)

Mulai sesi Claude Code baru di root repo, di branch `feat/remove-caddy`, dalam mode auto, lalu kirim:

```
/goal execute docs/superpowers/plans/2026-10-29-remove-caddy-goal.md
```

File itu berisi kriteria selesai, kondisi berhenti, prasyarat, langkah, aturan, dan format laporan akhir.

- **Gerbang deterministik (Stop hook Task 0b)** menjalankan semua pemeriksaan sendiri, dan menahan sesi sampai lulus.
- **`/goal`** menjaga sesi tetap bekerja lintas giliran, dan menilai dari keluaran yang tampil di percakapan.
- **Push dan PR** tetap di luar keadaan sukses, karena CLAUDE.md mewajibkan izin pemilik repo.
- **Penanda gerbang** `var/remove-caddy.goal` dipasang dan dicabut sendiri oleh runbook.
