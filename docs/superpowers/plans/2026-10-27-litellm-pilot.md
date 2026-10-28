# LiteLLM Pilot Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repo yang menjalankan pilot LiteLLM gateway (profil lokal dengan mock upstream dan profil VM dengan OpenAI), dikelola secara deklaratif oleh `gatewayctl`, dengan bukti uji T01–T11.

**Architecture:** Docker Compose menjalankan 2 replika LiteLLM, Postgres, Redis, dan Caddy, ditambah mock upstream di profil lokal. `gatewayctl` (Python) membaca `entitlements.yaml`, mengambil kondisi LiteLLM lewat management API, menghitung selisih dengan fungsi murni, lalu menerapkannya. Semua tool dan uji berjalan di container `tools`.

**Tech Stack:** Docker Compose, LiteLLM Proxy (≥ v1.93.0-stable, dipin digest), Postgres 16, Redis 7, Caddy 2, Python 3.12, pydantic v2, PyYAML, httpx, Typer, pytest, respx, FastAPI, uvicorn.

**Spec:** `docs/superpowers/specs/2026-10-27-litellm-pilot-design.md`

## Global Constraints

- Python 3.12; dependensi Python hanya yang ada di Tech Stack.
- Host hanya membutuhkan Docker dan `make`; semua perintah Python dijalankan di container `tools`.
- Image LiteLLM dipin ke digest, min. `v1.93.0-stable`. Catatan implementasi: LiteLLM tidak lagi menerbitkan tag `-stable` berversi (tidak ada `v1.93.0-stable`); yang dipin adalah `v1.106.4@sha256:c169fb3a…`, digest yang sama dengan `main-stable` per 2026-10-27.
- `LITELLM_MODE=PRODUCTION`; `allow_requests_on_db_unavailable` tidak pernah diaktifkan; response caching mati.
- `LITELLM_SALT_KEY` tidak pernah diganti setelah ada data; `init-local` menolak menimpa env yang sudah ada.
- Alias model: `company-fast` → `gpt-5.6-terra`, `company-coding` → `gpt-5.6-terra`, `company-reasoning` → `gpt-5.6-sol`. Fallback `company-reasoning` → `company-coding`.
- Harga per token: Terra input `2.5e-6`, output `15e-6`; Sol input `5e-6`, output `30e-6`.
- `num_retries: 2`, `request_timeout: 600`.
- Key mentah, master key, dan API key OpenAI tidak pernah ditulis ke log, audit, atau file repo.
- Resource buatan `gatewayctl` membawa metadata `{"managed_by": "gatewayctl"}`.
- Exit code `gatewayctl`: 0 sukses/tidak ada perubahan, 1 file tidak valid/aksi gagal/kesalahan pengguna, 2 `plan` ada perubahan, 3 LiteLLM tidak terjangkau atau master key ditolak, 4 aksi destruktif tanpa `--confirm`.
- Nilai sementara (spec bagian 10): reset budget UTC, toleransi overshoot 10%, pencabutan key ≤ 300 detik.
- File `*.env` (kecuali `*.env.example`), `deploy/certs/`, dan `var/` di-gitignore.

## Review Focus

1. **Huruf besar/spasi pada email member** (`Budi@Perusahaan.com ` vs `budi@perusahaan.com`): dinormalisasi ke huruf kecil tanpa spasi, dan duplikat terdeteksi. Diuji di Task 1.
2. **Team di file sudah ada di LiteLLM tetapi tidak dikelola `gatewayctl`**: `diff` menolak dengan `ConflictError`, bukan mengambil alih atau menimpa. Diuji di Task 2.
3. **Lebih dari 100 key di LiteLLM**: `list_keys` mengikuti paginasi sehingga tidak ada key yang terlewat (key terlewat berarti offboarding tidak memblokirnya). Diuji di Task 3.
4. **`LITELLM_MASTER_KEY` kosong atau salah**: exit 3 dengan pesan satu baris, tanpa traceback. Diuji di Task 4.
5. **`key issue` dengan label yang sudah dipakai**: exit 1 tanpa menerbitkan key kedua; stdout hanya berisi key mentah agar aman di-pipe. Diuji di Task 4.

---

## File Structure

| Path | Tanggung jawab |
| --- | --- |
| `gatewayctl/pyproject.toml` | Paket, dependensi, console script `gatewayctl`, extra `test` |
| `gatewayctl/src/gatewayctl/model.py` | Dataclass kondisi: desired dan actual |
| `gatewayctl/src/gatewayctl/schema.py` | Parsing dan validasi `entitlements.yaml`, `resolve()` ke `DesiredState` |
| `gatewayctl/src/gatewayctl/diff.py` | `diff()` murni → `Plan` |
| `gatewayctl/src/gatewayctl/client.py` | HTTP ke management API, redaksi rahasia |
| `gatewayctl/src/gatewayctl/state.py` | API → `ActualState` |
| `gatewayctl/src/gatewayctl/audit.py` | JSONL audit |
| `gatewayctl/src/gatewayctl/apply.py` | Menjalankan `Plan` |
| `gatewayctl/src/gatewayctl/keys.py` | `key issue/block/list` |
| `gatewayctl/src/gatewayctl/cli.py` | Typer CLI, exit code |
| `gatewayctl/tests/unit/` | Unit test per modul |
| `mock_upstream/` | `app.py`, `Dockerfile`, `tests/test_app.py` |
| `tools/Dockerfile` | Image `tools` |
| `deploy/` | Compose, `litellm/config.yaml`, Caddyfile, env example |
| `scripts/init-local.sh`, `scripts/t10-scan-logs.sh` | Pembuatan secret lokal; pemindaian log T10 |
| `entitlements/local.yaml`, `entitlements/pilot.yaml` | Entitlement uji dan pilot |
| `tests/helpers.py`, `tests/conftest.py` | Helper uji bersama |
| `tests/integration/`, `tests/acceptance/`, `tests/smoke/` | Lapisan uji |
| `docs/onboarding.md`, `docs/opencode.example.json`, `docs/pilot-checklist.md` | Dokumentasi |
| `Makefile`, `.gitignore` | Perintah operasi |

---

### Task 1: Scaffold `gatewayctl`, model, dan schema

**Files:**
- Create: `.gitignore`, `Makefile` (target `tools-build`, `unit`), `tools/Dockerfile`, `gatewayctl/pyproject.toml`, `gatewayctl/src/gatewayctl/__init__.py`, `gatewayctl/src/gatewayctl/model.py`, `gatewayctl/src/gatewayctl/schema.py`
- Test: `gatewayctl/tests/unit/test_schema.py`

**Interfaces:**
- Produces (`model.py`, semua `@dataclass(frozen=True)`):
  - `BudgetWindow(duration: str, max_usd: float)`
  - `KeyPolicy(models: frozenset[str], rpm_limit: int | None, budgets: tuple[BudgetWindow, ...])`
  - `TeamSpec(team_id: str, alias: str, models: frozenset[str], max_budget: float, budget_duration: str, rpm_limit: int)`
  - `MemberSpec(user_id: str, team_id: str, max_budget_in_team: float | None, kind: Literal["user", "service_account"] = "user")`
  - `DesiredState(teams: Mapping[str, TeamSpec], members: Mapping[str, MemberSpec], key_policies: Mapping[str, KeyPolicy])` — `members` dan `key_policies` dikunci `user_id`/nama service account
  - `ActualKey(token: str, key_alias: str | None, user_id: str | None, team_id: str | None, blocked: bool, policy: KeyPolicy, managed: bool, spend: float = 0.0)`
  - `ActualState(teams: Mapping[str, TeamSpec], managed_teams: frozenset[str], members: tuple[MemberSpec, ...], keys: tuple[ActualKey, ...])` — `members` hanya untuk team yang dikelola
- Produces (`schema.py`):
  - `class EntitlementsError(Exception)` dengan atribut `path: str`, `message: str`; `str(e) == f"{path}: {message}"`
  - `GatewayConfig(aliases: frozenset[str], fallbacks: Mapping[str, tuple[str, ...]])`
  - `load_gateway_config(path: Path) -> GatewayConfig` — membaca `model_list[].model_name` dan `router_settings.fallbacks`
  - `load_entitlements(path: Path, gateway: GatewayConfig) -> DesiredState` — parse, validasi, resolve
- Produces (`Makefile`): `make unit` membangun image `llm-gateway-tools` dan menjalankan `pytest gatewayctl/tests -q` di dalamnya dengan repo di-mount ke `/repo`. Task 5 menambahkan `mock_upstream/tests`.

- [ ] **Step 1: Buat scaffold**

`tools/Dockerfile`: `FROM python:3.12-slim`, pasang `git`, `COPY gatewayctl /repo/gatewayctl`, `pip install -e "/repo/gatewayctl[test]"`, `WORKDIR /repo`. Editable install memastikan source yang di-mount saat runtime yang dipakai. Extra `test` berisi `pytest`, `respx`, `fastapi`, `uvicorn`, `httpx`. `.gitignore` sesuai Global Constraints.

- [ ] **Step 2: Tulis test yang gagal**

Fixture `config` menulis:

```yaml
model_list: [{model_name: company-fast}, {model_name: company-coding}, {model_name: company-reasoning}]
router_settings: {fallbacks: [{"company-reasoning": ["company-coding"]}]}
```

```python
def test_spec_example_resolves(tmp_path, config):
    # isi file = contoh spec 6.1 persis
    s = load_entitlements(write(tmp_path, SPEC_EXAMPLE), config)
    assert s.teams["it-developer"] == TeamSpec("it-developer", "IT / Developer",
        frozenset({"company-fast", "company-coding", "company-reasoning"}), 500, "30d", 600)
    assert s.members["budi@perusahaan.com"] == MemberSpec("budi@perusahaan.com", "it-developer", 100)
    assert s.members["sari@perusahaan.com"].max_budget_in_team == 150
    assert s.key_policies["budi@perusahaan.com"] == KeyPolicy(
        frozenset({"company-fast", "company-coding", "company-reasoning"}), 60,
        (BudgetWindow("24h", 10), BudgetWindow("30d", 100)))
    assert s.members["svc-helpdesk-bot"] == MemberSpec("svc-helpdesk-bot", "it-developer", None, "service_account")
    assert s.key_policies["svc-helpdesk-bot"] == KeyPolicy(frozenset({"company-fast"}), 120, (BudgetWindow("30d", 50),))

def test_member_key_override_merges_fieldwise(...):
    # member {user_id: rate1@x.test, key: {rpm_limit: 3}} → rpm 3, budgets dan models dari default

def test_unknown_alias(...):        # teams.finance.models[1] = company-x
    assert err.path == "teams.finance.models[1]" and "company-x" in err.message
def test_key_models_not_subset(...):  # path "teams.finance.members[0].key.models"
def test_fallback_target_missing(...):  # team punya company-reasoning tanpa company-coding; path "teams.x.models", pesan memuat "company-coding"
def test_user_in_two_teams(...):       # path "teams.b.members[0]"
def test_service_account_collides_with_user(...):  # path "service_accounts.budi@perusahaan.com"
def test_service_account_unknown_team(...):        # path "service_accounts.svc.team"
def test_member_ids_normalized(...):   # "  Budi@Perusahaan.com " → "budi@perusahaan.com"; bila juga ada "budi@perusahaan.com" di team lain → error duplikat
def test_team_id_format(...):          # "IT Dev" ditolak; pola ^[a-z0-9][a-z0-9-]*$
def test_budget_duration_format(...):  # "1 week" ditolak; pola ^\d+[hd]$
def test_version_must_be_1(...):
```

- [ ] **Step 3: Jalankan, pastikan gagal**

Run: `make unit` — Expected: FAIL, `ImportError` pada `gatewayctl.schema`.

- [ ] **Step 4: Implementasikan `model.py` dan `schema.py`**

Model pydantic internal di `schema.py` dengan `before`-validator yang mengubah member string menjadi `{"user_id": ...}` dan menormalisasi `user_id` (strip + lower). Error pydantic dikonversi ke `EntitlementsError` dengan `loc` digabung titik dan indeks sebagai `[i]`. Validasi silang (alias, subset, fallback, duplikat, service account) dijalankan setelah parsing dan melempar error pertama yang ditemukan.

- [ ] **Step 5: Jalankan, pastikan lulus**

Run: `make unit` — Expected: semua test di `test_schema.py` PASS.

- [ ] **Step 6: Commit**

```bash
git add .gitignore Makefile tools gatewayctl
git commit -m "feat(gatewayctl): entitlements schema and desired state"
```

---

### Task 2: `diff()` murni

**Files:**
- Create: `gatewayctl/src/gatewayctl/diff.py`
- Test: `gatewayctl/tests/unit/test_diff.py`

**Interfaces:**
- Consumes: semua dataclass `model.py` (Task 1).
- Produces:
  - `ActionKind = Literal["create_team", "update_team", "add_member", "update_member", "update_key", "block_key", "remove_member", "delete_team"]` — urutan literal ini adalah urutan eksekusi
  - `Action(kind: ActionKind, target: str, before: Mapping | None, after: Mapping | None, destructive: bool)` (frozen)
  - `Plan(actions: tuple[Action, ...], unmanaged: tuple[str, ...], orphan_teams: tuple[str, ...])` (frozen)
  - `class ConflictError(Exception)`
  - `diff(desired: DesiredState, actual: ActualState, *, prune: bool = False) -> Plan`
  - Format `target`: `team:<id>`, `member:<team_id>/<user_id>`, `key:<key_alias atau token[:8]>`
  - Bentuk `after`/`before`:
    - team: `{"team_id", "alias", "models": sorted list, "max_budget", "budget_duration", "rpm_limit"}`
    - member: `{"team_id", "user_id", "max_budget_in_team"}`
    - key (`update_key`): `{"token", "models": sorted list, "rpm_limit", "budgets": [{"duration", "max_usd"}]}`
    - `block_key`: `before={"token", "key_alias", "user_id", "team_id"}`, `after=None`

Aturan yang belum ditentukan oleh signature:
- Key dengan `managed=False` dilewati dan masuk `unmanaged`; key yang sudah `blocked` dilewati.
- Key dikelola diblokir bila pemiliknya tidak ada di `desired.members` atau `team_id`-nya berbeda dari team pemilik di desired (user pindah team).
- `update_team` dan `update_key` destruktif hanya bila ada model yang hilang (`before.models - after.models` tidak kosong).
- Team di `actual.teams` tanpa tanda kelola masuk `unmanaged`; bila team itu juga ada di desired → `ConflictError`.
- Team dikelola yang tidak ada di desired: tanpa `prune` masuk `orphan_teams` dan member/key-nya tidak disentuh; dengan `prune` → `block_key` untuk key aktifnya, `remove_member` untuk member-nya, `delete_team`.
- Urutan: berdasarkan posisi `kind` dalam `ActionKind`, lalu `target`.

- [ ] **Step 1: Tulis test yang gagal** (uji tabel; builder kecil `team()`, `member()`, `key()` di file test)

```python
def test_empty_actual_creates_everything():
    assert [a.kind for a in plan.actions] == ["create_team", "add_member", "add_member"]
def test_in_sync_is_empty():                      # plan.actions == ()
def test_team_budget_change_is_nondestructive_update()
def test_team_model_removed_is_destructive()     # destructive True
def test_member_budget_change_updates_member()
def test_removed_member_is_removed_and_keys_blocked():
    assert kinds == ["block_key", "remove_member"] and all(a.destructive for a in plan.actions)
def test_member_moved_team_blocks_old_key():      # remove_member lama, add_member baru, block_key
def test_key_policy_drift_updates_key()          # after.budgets == [{"duration": "24h", "max_usd": 10}, ...]
def test_blocked_and_unmanaged_keys_untouched()  # unmanaged == ("key:legacy",)
def test_unmanaged_team_listed_not_touched()
def test_desired_team_exists_unmanaged_raises_conflict()   # Review Focus 2
def test_orphan_team_without_prune_listed()      # orphan_teams == ("ops",), actions == ()
def test_orphan_team_with_prune():               # kinds == ["block_key", "remove_member", "delete_team"]
def test_actions_ordered_by_kind_then_target()
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `make unit`, Expected: FAIL `ImportError`.
- [ ] **Step 3: Implementasikan `diff()`** sesuai aturan di atas.
- [ ] **Step 4: Jalankan, pastikan lulus** — `make unit`, Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(gatewayctl): pure diff of desired vs actual state"`

---

### Task 3: `client.py` dan `state.py`

**Files:**
- Create: `gatewayctl/src/gatewayctl/client.py`, `gatewayctl/src/gatewayctl/state.py`
- Test: `gatewayctl/tests/unit/test_client.py`, `gatewayctl/tests/unit/test_state.py`

**Interfaces:**
- Consumes: `model.py` (Task 1).
- Produces (`client.py`):
  - `class GatewayUnavailable(Exception)`; `class ApiError(Exception)` dengan `status: int`, `path: str`, `detail: str`
  - `redact(text: str, secrets: Iterable[str]) -> str` — mengganti setiap secret dan setiap pola `sk-[A-Za-z0-9_-]{6,}` dengan `sk-***`
  - `class LiteLLMClient(base_url: str, master_key: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 30.0)`:

    | Metode | HTTP |
    | --- | --- |
    | `check() -> None` | `GET /key/list?size=1`; error koneksi atau 401/403 → `GatewayUnavailable` |
    | `list_teams() -> list[dict]` | `GET /team/list` |
    | `team_info(team_id: str) -> dict` | `GET /team/info?team_id=` |
    | `list_keys() -> list[dict]` | `GET /key/list?return_full_object=true&page=N&size=100`, ulangi hingga `page >= total_pages` |
    | `key_info(key: str) -> dict` | `GET /key/info?key=` |
    | `team_new(payload: dict) -> dict` | `POST /team/new` |
    | `team_update(payload: dict) -> dict` | `POST /team/update` |
    | `team_delete(team_id: str) -> None` | `POST /team/delete` `{"team_ids": [team_id]}` |
    | `member_add(team_id: str, user_id: str, max_budget_in_team: float \| None) -> None` | `POST /team/member_add` |
    | `member_update(team_id: str, user_id: str, max_budget_in_team: float \| None) -> None` | `POST /team/member_update` |
    | `member_delete(team_id: str, user_id: str) -> None` | `POST /team/member_delete` |
    | `key_generate(payload: dict) -> dict` | `POST /key/generate`; hasil memuat `key` dan `token` |
    | `key_update(payload: dict) -> None` | `POST /key/update` |
    | `key_block(token: str) -> None` | `POST /key/block` `{"key": token}` |

    Respons non-2xx lain → `ApiError` dengan `detail` yang sudah melewati `redact`.
- Produces (`state.py`):
  - `fetch_actual(client: LiteLLMClient) -> ActualState`
  - `team_spec_from_api(team: dict) -> TeamSpec`
  - `key_from_api(key: dict) -> ActualKey`

Pemetaan field API (diverifikasi terhadap versi yang dipin di Task 7):

| Model | Field API |
| --- | --- |
| `TeamSpec` | `team_id`, `team_alias`, `models`, `max_budget`, `budget_duration`, `rpm_limit`; dikelola bila `metadata.managed_by == "gatewayctl"` |
| `MemberSpec` | dari `team_info`: `team_memberships[].user_id` + `litellm_budget_table.max_budget` |
| `ActualKey` | `token`, `key_alias`, `user_id`, `team_id`, `blocked` (null = False), `spend`, `models`, `rpm_limit`, `budget_limits[]{budget_duration, max_budget}`, `metadata.managed_by` |

- [ ] **Step 1: Tulis test yang gagal** (dengan `respx`)

```python
def test_list_keys_follows_pagination():          # Review Focus 3: 3 halaman (100, 100, 37) → len == 237
def test_check_raises_unavailable_on_connect_error()
def test_check_raises_unavailable_on_401()
def test_api_error_detail_redacted():
    # body error memuat master key dan "Bearer sk-abcdef123456" → "sk-***", master key tidak muncul
def test_authorization_header_sent()              # "Bearer <master>"
def test_fetch_actual_maps_fields():              # fixture JSON per endpoint → ActualState yang diharapkan
def test_member_budget_from_team_info()
def test_team_without_metadata_is_unmanaged()
def test_blocked_null_is_false()
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `make unit`.
- [ ] **Step 3: Implementasikan `client.py` dan `state.py`.** `fetch_actual` memanggil `team_info` hanya untuk team yang dikelola.
- [ ] **Step 4: Jalankan, pastikan lulus** — `make unit`.
- [ ] **Step 5: Commit** — `git commit -m "feat(gatewayctl): LiteLLM client and actual state"`

---

### Task 4: Audit, apply, operasi key, dan CLI

**Files:**
- Create: `gatewayctl/src/gatewayctl/audit.py`, `apply.py`, `keys.py`, `cli.py`; console script `gatewayctl = "gatewayctl.cli:app"` di `pyproject.toml`
- Test: `gatewayctl/tests/unit/test_audit.py`, `test_apply.py`, `test_keys.py`, `test_cli.py`

**Interfaces:**
- Consumes: `load_gateway_config`, `load_entitlements`, `EntitlementsError` (Task 1); `diff`, `Plan`, `Action`, `ConflictError` (Task 2); `LiteLLMClient`, `GatewayUnavailable`, `ApiError`, `fetch_actual` (Task 3).
- Produces:
  - `AuditLog(path: Path, operator: str, git_sha: str)` dengan `record(action: str, target: str, before: Mapping | None, after: Mapping | None) -> None` — menambahkan satu baris JSON `{"ts", "operator", "git_sha", "action", "target", "before", "after"}`, `ts` ISO-8601 UTC; membuat direktori induk bila belum ada
  - `class ApplyError(Exception)` dengan `done: int`, `action: Action`, `cause: Exception`
  - `execute(plan: Plan, client: LiteLLMClient, audit: AuditLog) -> int` — menjalankan aksi berurutan, `record` setelah setiap aksi berhasil, berhenti dan melempar `ApplyError` pada kegagalan pertama
  - `issue_key(desired: DesiredState, actual: ActualState, client: LiteLLMClient, audit: AuditLog, owner: str, label: str) -> str` — mengembalikan key mentah
  - `block_keys(actual: ActualState, client: LiteLLMClient, audit: AuditLog, *, user_id: str | None = None, alias: str | None = None) -> list[str]` — token yang diblokir
  - `key_rows(actual: ActualState, *, user_id: str | None = None, team_id: str | None = None) -> list[dict]` — kolom `key_alias`, `user_id`, `team_id`, `blocked`, `spend`
  - CLI `gatewayctl [--file PATH] [--config PATH] [--base-url URL] COMMAND`:

    | Opsi | Env | Default |
    | --- | --- | --- |
    | `--file` | `GATEWAYCTL_FILE` | wajib |
    | `--config` | — | `deploy/litellm/config.yaml` |
    | `--base-url` | `LITELLM_BASE_URL` | `http://litellm-a:4000` |
    | master key | `LITELLM_MASTER_KEY` | wajib untuk perintah yang memanggil API |
    | operator | `GATEWAYCTL_OPERATOR` | wajib untuk `apply`, `key issue`, `key block` |
    | audit log | `GATEWAYCTL_AUDIT_LOG` | `var/audit.log` |
    | git SHA | `GATEWAYCTL_GIT_SHA` | `unknown` |

    Perintah: `plan [--json] [--prune]`, `apply [--confirm] [--prune]`, `key issue --user U --label L`, `key block (--user U | --alias A)`, `key list [--user U] [--team T]`.

Pemetaan aksi ke API di `apply.py`:

| Aksi | Panggilan |
| --- | --- |
| `create_team` / `update_team` | `team_new` / `team_update` dengan `{"team_id", "team_alias", "models", "max_budget", "budget_duration", "rpm_limit", "metadata": {"managed_by": "gatewayctl"}}` |
| `add_member` / `update_member` / `remove_member` | `member_add` / `member_update` / `member_delete` |
| `update_key` | `key_update({"key": token, "models", "rpm_limit", "budget_limits": [{"budget_duration", "max_budget"}], "metadata": {"managed_by": "gatewayctl"}})` |
| `block_key` | `key_block(token)` |
| `delete_team` | `team_delete(team_id)` |

`issue_key` memanggil `key_generate` dengan `{"user_id", "team_id", "key_alias": f"{owner}-{label}", "models", "rpm_limit", "budget_limits", "metadata": {"managed_by": "gatewayctl", "owner_kind": kind}}`. Ditolak (`ValueError`) bila pemilik tidak ada di desired atau alias sudah ada di `actual.keys`. Audit mencatat alias dan `token`, tidak pernah key mentah.

Keluaran `plan`: satu baris per aksi, `+` untuk create/add, `~` untuk update, `-` untuk block/remove/delete, akhiran `[destructive]`; lalu daftar unmanaged dan orphan; lalu ringkasan jumlah. `--json` mengeluarkan `{"actions": [...], "unmanaged": [...], "orphan_teams": [...]}`. Semua keluaran selain key mentah dari `key issue` dikirim ke stderr.

- [ ] **Step 1: Tulis test yang gagal**

```python
# test_audit.py
def test_record_appends_jsonl_line(tmp_path)        # 2 record → 2 baris, field lengkap, ts berakhiran "+00:00"
# test_apply.py (fake client yang mencatat panggilan)
def test_execute_calls_in_plan_order_and_audits()
def test_create_team_payload_has_managed_metadata()
def test_execute_stops_on_first_failure():          # aksi ke-2 gagal → ApplyError.done == 1, aksi ke-3 tidak dipanggil, audit 1 baris
# test_keys.py
def test_issue_key_uses_policy_and_alias()          # key_alias "budi@perusahaan.com-opencode", budget_limits sesuai policy
def test_issue_key_unknown_owner_rejected()
def test_issue_key_existing_alias_rejected()        # Review Focus 5: key_generate tidak dipanggil
def test_audit_never_contains_raw_key()
def test_block_by_user_blocks_all_active_keys()
# test_cli.py (typer CliRunner, client di-patch)
def test_plan_exit_0_when_in_sync()
def test_plan_exit_2_when_changes()
def test_invalid_file_exit_1_with_path()            # stderr memuat "teams.finance.models[1]"
def test_missing_master_key_exit_3_no_traceback()   # Review Focus 4: stderr satu baris, tanpa "Traceback"
def test_unavailable_exit_3()
def test_destructive_without_confirm_exit_4_and_no_calls()
def test_apply_failure_exit_1()
def test_apply_requires_operator()                  # exit 1
def test_key_issue_stdout_is_only_the_key()         # Review Focus 5: stdout == "sk-xyz\n"
def test_key_issue_alias_exists_exit_1()
def test_conflict_error_exit_1()
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `make unit`.
- [ ] **Step 3: Implementasikan `audit.py`, `apply.py`, `keys.py`, `cli.py`.** `cli.py` adalah satu-satunya tempat yang menerjemahkan exception ke exit code; `client.check()` dipanggil sebelum `fetch_actual`.
- [ ] **Step 4: Jalankan, pastikan lulus** — `make unit`.
- [ ] **Step 5: Commit** — `git commit -m "feat(gatewayctl): apply, key operations, and CLI"`

---

### Task 5: Mock upstream

**Files:**
- Create: `mock_upstream/app.py`, `mock_upstream/Dockerfile`
- Modify: `Makefile` (`unit` juga menjalankan `mock_upstream/tests`)
- Test: `mock_upstream/tests/test_app.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI`; `app = create_app()` di level modul. Service `mock-upstream`, port 8080.

| Endpoint | Perilaku |
| --- | --- |
| `POST /v1/chat/completions` | Jalur sukses: tanpa stream mengembalikan `chat.completion` dengan `model` dari request, isi `"mock-ok"`, `usage` default `{"prompt_tokens": 1000, "completion_tokens": 500}` (biaya Terra = $0.01, Sol = $0.02). Bila request memuat `tools`: `message.tool_calls = [{"id": "call_mock_1", "type": "function", "function": {"name": tools[0].function.name, "arguments": "{}"}}]`, `finish_reason: "tool_calls"`. Dengan stream: SSE 5 chunk `mock-0`..`mock-4`, chunk akhir memuat `usage`, lalu `data: [DONE]`. |
| `GET /v1/models` | `gpt-5.6-terra`, `gpt-5.6-sol` |
| `POST /_mock/scenario` | `{"model", "mode", "count", "delay_ms": 0}`; berlaku untuk `count` request berikutnya ke model itu, lalu kembali `ok` |
| `POST /_mock/usage` | `{"prompt_tokens", "completion_tokens"}` |
| `GET /_mock/requests` | `[{"model", "stream", "has_tools", "ts", "auth_hash"}]`; `auth_hash` = 16 karakter pertama sha256 dari nilai header `Authorization` |
| `POST /_mock/reset` | Menghapus scenario, request, dan usage kustom |

Mode: `error_429` → 429 `{"error": {"type": "rate_limit_error", "code": "rate_limit_exceeded", "message": "mock"}}`; `error_500` → 500 `server_error`; `fail_before_stream` → 503 sebelum mengirim byte apa pun; `fail_mid_stream` → pada request stream, kirim 2 chunk lalu putus koneksi; pada request tanpa stream, 500; `slow` → tunggu `delay_ms`, lalu sukses. Setiap request tercatat, termasuk yang gagal.

- [ ] **Step 1: Tulis test yang gagal** (FastAPI `TestClient`)

```python
def test_ok_nonstream_usage_and_model()
def test_stream_yields_5_chunks_then_usage_then_done()
def test_tools_returns_tool_call_named_after_first_tool()
def test_scenario_error_429_applies_count_times_then_ok()   # 2× 429 lalu 200
def test_scenario_is_per_model()                              # sol gagal, terra tetap 200
def test_fail_mid_stream_sends_two_chunks_then_breaks()
def test_requests_recorded_with_auth_hash_not_raw()           # raw header tidak muncul di JSON
def test_reset_clears_everything()
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `make unit`.
- [ ] **Step 3: Implementasikan `app.py` dan `Dockerfile`** (`python:3.12-slim`, `fastapi`, `uvicorn`, `CMD uvicorn app:app --host 0.0.0.0 --port 8080`). State di memori dilindungi `threading.Lock`.
- [ ] **Step 4: Jalankan, pastikan lulus** — `make unit`.
- [ ] **Step 5: Commit** — `git commit -m "feat: configurable OpenAI mock upstream"`

---

### Task 6: Stack deploy (lokal dan VM)

**Files:**
- Create: `deploy/compose.yaml`, `deploy/compose.local.yaml`, `deploy/compose.vm.yaml`, `deploy/litellm/config.yaml`, `deploy/caddy/Caddyfile.local`, `deploy/caddy/Caddyfile.vm`, `deploy/env/local.env.example`, `deploy/env/vm.env.example`, `scripts/init-local.sh`
- Modify: `Makefile` (target `init-local`, `up`, `down`, `ps`, `logs`, `config`)

**Interfaces:**
- Produces:
  - Service: `litellm-a`, `litellm-b`, `postgres`, `redis`, `caddy`, `mock-upstream` (lokal), `tools` (profil `tools`)
  - `COMPOSE = docker compose -p llm-gateway-$(ENV) -f deploy/compose.yaml -f deploy/compose.$(ENV).yaml --env-file deploy/env/$(ENV).env`, `ENV ?= local`
  - Hostname lokal: `llm.pilot.test`, `llm-admin.pilot.test` (alias jaringan pada `caddy`); host: `127.0.0.1:8443`
  - Env file: `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_API_BASE`, `LLM_HOST`, `LLM_ADMIN_HOST`; VM menambahkan `VPN_CIDR`, `TLS_CERT_DIR`
  - Env untuk `tools`: `LITELLM_BASE_URL=http://litellm-a:4000`, `GATEWAY_URL=https://${LLM_HOST}`, `GATEWAY_CA_BUNDLE=/caddy-data/caddy/pki/authorities/local/root.crt` (lokal), `MOCK_URL=http://mock-upstream:8080` (lokal), ditambah env file profil

Ketentuan:
- `litellm-a` dan `litellm-b` berbagi definisi lewat YAML anchor `x-litellm`. `litellm-b` memakai `DISABLE_SCHEMA_UPDATE=true` dan `depends_on: litellm-a: condition: service_healthy` agar migrasi hanya berjalan sekali. Healthcheck: `python -c "import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness')"`.
- `postgres` dan `redis` tanpa `ports`; healthcheck `pg_isready` dan `redis-cli -a $REDIS_PASSWORD ping`.
- `config.yaml` = panduan 5.2 ditambah: `api_base: os.environ/OPENAI_API_BASE`, `model_info` dengan harga di Global Constraints, `router_settings.disable_cooldowns: true` (satu deployment per alias; cooldown akan membuat alias mati setelah uji kegagalan), `litellm_settings: {request_timeout: 600, turn_off_message_logging: true, json_logs: true, cache: false}`, `general_settings.store_prompts_in_spend_logs: false`. Container memakai `LITELLM_LOG=INFO` dan `LITELLM_MODE=PRODUCTION`.
- Caddy: `{$LLM_HOST}` hanya meneruskan `path /v1/chat/completions /v1/models /health/liveliness` ke `litellm-a:4000 litellm-b:4000` dengan `lb_policy round_robin`, health check aktif `/health/liveliness`, `flush_interval -1`, `transport http { read_timeout 600s }`; path lain `respond 404`. `{$LLM_ADMIN_HOST}` meneruskan semuanya. Lokal: `tls internal`, port `127.0.0.1:8443:443`. VM: `tls /certs/fullchain.pem /certs/privkey.pem`, admin hanya dari `remote_ip {$VPN_CIDR}` (selain itu 403), port 80/443. Access log ke stdout.
- Image LiteLLM dipin ke digest: ambil tag `v1.93.x-stable` terbaru dengan `docker buildx imagetools inspect ghcr.io/berriai/litellm:<tag>`, tulis tag dan digest di `compose.yaml`. Catatan implementasi: LiteLLM tidak lagi menerbitkan tag `-stable` berversi (tidak ada `v1.93.0-stable`); yang dipin adalah `v1.106.4@sha256:c169fb3a…`, digest yang sama dengan `main-stable` per 2026-10-27.
- `scripts/init-local.sh` menolak bila `deploy/env/local.env` sudah ada; membuat `LITELLM_MASTER_KEY=sk-<hex32>`, `LITELLM_SALT_KEY=sk-<hex32>`, password acak, `OPENAI_API_KEY=sk-mock-<hex16>`, `OPENAI_API_BASE=http://mock-upstream:8080/v1`.

- [ ] **Step 1: Tulis file deploy dan target Makefile** sesuai ketentuan.
- [ ] **Step 2: Validasi konfigurasi kedua profil**

Run: `make config ENV=local && cp deploy/env/vm.env.example /tmp/vm.env && docker compose -f deploy/compose.yaml -f deploy/compose.vm.yaml --env-file /tmp/vm.env config -q`
Expected: tanpa error.

- [ ] **Step 3: Jalankan stack lokal**

Run: `make init-local && make up && make ps`
Expected: semua service `healthy`/`running`; menjalankan `make init-local` kedua kali gagal dengan pesan bahwa file sudah ada.

- [ ] **Step 4: Verifikasi routing**

Run (dari host, dengan `MASTER=$(grep ^LITELLM_MASTER_KEY= deploy/env/local.env | cut -d= -f2-)`):
- `curl -sk --resolve llm.pilot.test:8443:127.0.0.1 https://llm.pilot.test:8443/health/liveliness` → 200
- `curl -sk -o /dev/null -w '%{http_code}' --resolve llm.pilot.test:8443:127.0.0.1 https://llm.pilot.test:8443/key/list` → `404`
- `curl -sk --resolve llm-admin.pilot.test:8443:127.0.0.1 -H "Authorization: Bearer $MASTER" https://llm-admin.pilot.test:8443/key/list` → 200 JSON
- `curl -sk --resolve llm.pilot.test:8443:127.0.0.1 -H "Authorization: Bearer $MASTER" https://llm.pilot.test:8443/v1/chat/completions -d '{"model":"company-fast","messages":[{"role":"user","content":"hi"}]}'` → jawaban `mock-ok`

- [ ] **Step 5: Commit** — `git commit -m "feat(deploy): compose stack with local and VM profiles"`

---

### Task 7: Uji integrasi `gatewayctl` terhadap stack

**Files:**
- Create: `entitlements/local.yaml`, `tests/helpers.py`, `tests/conftest.py`, `tests/integration/test_gatewayctl.py`
- Modify: `Makefile` (target `apply`, `plan`, `ctl`, `test`)

**Interfaces:**
- Consumes: CLI (Task 4), `LiteLLMClient` (Task 3), stack (Task 6), mock (Task 5).
- Produces (`tests/helpers.py`):
  - `gateway(key: str) -> httpx.Client` — base `GATEWAY_URL`, `verify=GATEWAY_CA_BUNDLE`, tanpa retry
  - `replica(name: Literal["litellm-a", "litellm-b"], key: str) -> httpx.Client` — `http://<name>:4000`
  - `chat(client: httpx.Client, model: str, *, stream: bool = False, tools: list | None = None, prompt: str = "ping") -> httpx.Response`
  - `class Mock`: `reset()`, `scenario(model: str, mode: str, count: int, delay_ms: int = 0)`, `requests() -> list[dict]`
  - `run_ctl(*args: str, file: Path = LOCAL_ENTITLEMENTS) -> subprocess.CompletedProcess` — env `GATEWAYCTL_OPERATOR=test@local`
  - `issue_key(user: str) -> str` — label unik `t-<uuid6>`
  - `admin() -> LiteLLMClient`
- Produces (`tests/conftest.py`): fixture session `applied` (menjalankan `apply --confirm` pada `local.yaml`) dan fixture `mock` (reset sebelum setiap test).
- Produces (`entitlements/local.yaml`):

| Team | Models | Member dan override key |
| --- | --- | --- |
| `it-developer` | ketiga alias | `dev1@local.test`, `dev2@local.test` (default key: rpm 60, 24h $10, 30d $100) |
| `finance` | `company-fast` | `fin1@local.test` |
| `qa-limits` (budget $10/30d) | `company-fast` | `budget1@local.test` key 30d $0.05; `parallel1@local.test` key 30d $0.10; `rate1@local.test` key rpm 3 |
| service account `svc-test` | `company-fast` | team `it-developer`, rpm 120, 30d $5 |

- `Makefile`: `FILE ?= entitlements/local.yaml` untuk `ENV=local` dan `entitlements/pilot.yaml` untuk `ENV=vm`; `make plan`/`make apply ARGS=--confirm` menjalankan `gatewayctl --file $(FILE) plan|apply $(ARGS)` di `tools` dengan `GATEWAYCTL_OPERATOR=$(OPERATOR)` (default `git config user.email`) dan `GATEWAYCTL_GIT_SHA` = `git log -1 --format=%H -- $(FILE)`. `make ctl ARGS='...'` menjalankan `gatewayctl --file $(FILE) $(ARGS)` dengan env yang sama (untuk `key issue/block/list`).
- `make test` = `$(COMPOSE) run --rm tools pytest tests/integration tests/acceptance -v`, lalu `scripts/t10-scan-logs.sh $(ENV)` (Task 8).

- [ ] **Step 1: Tulis test**

```python
def test_apply_is_idempotent(applied):
    assert run_ctl("apply", "--confirm").returncode == 0
    assert run_ctl("plan").returncode == 0

def test_litellm_fields_roundtrip(applied):
    key = issue_key("dev1@local.test")
    info = admin().key_info(key)["info"]
    assert {(b["budget_duration"], b["max_budget"]) for b in info["budget_limits"]} == {("24h", 10), ("30d", 100)}
    assert info["metadata"]["managed_by"] == "gatewayctl"
    members = admin().team_info("it-developer")["team_memberships"]
    # entri dev1@local.test: litellm_budget_table.max_budget == 100

def test_removed_member_is_offboarded(applied, tmp_path):
    # salin local.yaml + member tmp-off@local.test → apply → issue_key → chat 200
    # hapus member dari salinan → plan exit 2 memuat "block_key" dan "remove_member"
    # apply tanpa --confirm → exit 4; dengan --confirm → exit 0; chat → 401
    # akhiri dengan apply local.yaml asli dan plan exit 0

def test_unmanaged_team_untouched(applied):
    # admin().team_new({"team_id": "legacy-x", "models": ["company-fast"]}) tanpa metadata
    # plan --json → "team:legacy-x" di unmanaged, exit 0; apply tidak mengubahnya
```

- [ ] **Step 2: Jalankan**

Run: `make up && make test`
Expected: semua PASS. **Bila `test_litellm_fields_roundtrip` gagal karena field `budget_limits`, `max_budget_in_team`, atau `metadata` tidak ada atau berbeda nama di versi yang dipin, berhenti dan laporkan.** Jangan mengganti mekanisme budget diam-diam; ini risiko yang dicatat di spec bagian 11. Bila hanya nama field berbeda, perbaiki pemetaan di `state.py`/`apply.py`/`keys.py` beserta unit test-nya.

- [ ] **Step 3: Commit** — `git commit -m "test: gatewayctl integration against local stack"`

---

### Task 8: Acceptance T01–T05, T08–T10

**Files:**
- Create: `tests/acceptance/test_access.py` (T01, T04), `tests/acceptance/test_budget.py` (T02, T03), `tests/acceptance/test_revocation.py` (T05), `tests/acceptance/test_resilience.py` (T08, T09), `tests/acceptance/test_log_hygiene.py` (T10), `scripts/t10-scan-logs.sh`

**Interfaces:**
- Consumes: `tests/helpers.py`, fixture `applied` dan `mock` (Task 7).
- Produces: `var/t10-sentinels.txt` (satu nilai per baris) yang ditulis T10 dan dibaca `scripts/t10-scan-logs.sh`.

- [ ] **Step 1: Tulis test**

```python
def test_t01_finance_cannot_use_reasoning(applied, mock):
    r = chat(gateway(issue_key("fin1@local.test")), "company-reasoning")
    assert r.status_code in (401, 403) and "company-reasoning" in r.text
    assert mock.requests() == []

def test_t04_rate_limit_from_gateway(applied, mock):
    # key rate1 (rpm 3): 6 request berturut-turut
    assert 429 in statuses
    assert len(mock.requests()) == statuses.count(200)

def test_t02_budget_exhausted(applied, mock):
    # key budget1 ($0.05, $0.01/request): request berurutan, jeda 1 detik, maks. 30
    assert successes >= 5
    assert last.status_code != 200 and "budget_exceeded" in last.text

def test_t03_parallel_overshoot_within_tolerance(applied, mock):
    # key parallel1 ($0.10): 20 request paralel (ThreadPoolExecutor), lewat Caddy (dua replika)
    # tunggu spend stabil: key_info dibaca tiap 2 detik hingga dua bacaan sama, maks. 30 detik
    overshoot = (spend - 0.10) / 0.10
    print(f"T03 spend={spend:.4f} overshoot={overshoot:.1%}")
    assert overshoot <= 0.10

def test_t05_block_propagates_to_all_replicas(applied, mock):
    # dev2: request sukses ke litellm-a dan litellm-b (cache key terisi)
    # run_ctl("key", "block", "--alias", alias)
    # poll kedua replika tiap 5 detik hingga keduanya 401, maks. 300 detik
    print(f"T05 revocation seconds={elapsed:.0f}")
    assert elapsed <= 300

def test_t08_retry_then_success(applied, mock):
    mock.scenario("gpt-5.6-terra", "error_429", 2)
    assert chat(..., "company-fast").status_code == 200 and len(mock.requests()) == 3
def test_t08_retry_exhausted(applied, mock):
    mock.scenario("gpt-5.6-terra", "error_429", 5)
    assert chat(..., "company-fast").status_code == 429 and len(mock.requests()) == 3

def test_t09_fallback_before_stream(applied, mock):
    mock.scenario("gpt-5.6-sol", "fail_before_stream", 3)   # semua percobaan Sol gagal
    r = chat(gateway(issue_key("dev1@local.test")), "company-reasoning", stream=True)
    assert r.status_code == 200 and "mock-4" in r.text
    assert [q["model"] for q in mock.requests()][-1] == "gpt-5.6-terra"
def test_t09_no_fallback_mid_stream(applied, mock):
    mock.scenario("gpt-5.6-sol", "fail_mid_stream", 1)
    # stream berakhir dengan error atau tanpa [DONE]
    assert all(q["model"] == "gpt-5.6-sol" for q in mock.requests())

def test_t10_traffic_with_sentinels(applied, mock):
    # prompt = f"SENTINEL-PROMPT-{uuid4()}", key baru; satu request stream dan satu non-stream
    # tulis prompt sentinel dan key mentah ke var/t10-sentinels.txt
    # auth_hash di mock == sha256("Bearer " + OPENAI_API_KEY)[:16] dan != hash virtual key
```

`scripts/t10-scan-logs.sh ENV`: membaca `var/t10-sentinels.txt`, menambahkan nilai `LITELLM_MASTER_KEY` dan `OPENAI_API_KEY` dari env file, lalu mencari setiap nilai (`grep -F`) di `$(COMPOSE) logs --no-color litellm-a litellm-b caddy postgres redis` dan di `COPY (SELECT * FROM "LiteLLM_SpendLogs") TO STDOUT` lewat `$(COMPOSE) exec -T postgres psql`. Log `mock-upstream` dikecualikan karena memang menerima prompt. Exit 1 dengan nama sumber bila ada yang ditemukan, tanpa mencetak nilai rahasianya.

- [ ] **Step 2: Jalankan**

Run: `make test`
Expected: semua PASS, termasuk scan T10 (`T10 clean`). Catat keluaran `T03 ...` dan `T05 ...`.

Bila T03 gagal karena overshoot melebihi 10%, **jangan longgarkan ambang**. Laporkan angka aktualnya; ini temuan untuk Gate 2 (spec bagian 10). Bila T09 menunjukkan fallback terjadi di tengah stream, laporkan; jangan ubah uji.

- [ ] **Step 3: Commit** — `git commit -m "test: acceptance T01-T05, T08-T10 against mock upstream"`

---

### Task 9: Smoke OpenAI asli, entitlement pilot, dan dokumentasi

**Files:**
- Create: `tests/smoke/test_smoke.py`, `tests/smoke/spend_report.py`, `entitlements/pilot.yaml`, `docs/onboarding.md`, `docs/opencode.example.json`, `docs/pilot-checklist.md`
- Modify: `Makefile` (target `smoke`)

**Interfaces:**
- Consumes: `tests/helpers.py` (Task 7), stack profil VM (Task 6).
- Produces:
  - `make smoke ENV=vm` = `$(COMPOSE) run --rm -e SMOKE_KEY tools pytest tests/smoke -v`
  - `python tests/smoke/spend_report.py [--compare BEFORE.json]` — tanpa `--compare` mencetak JSON `{"ts", "teams": {team_id: spend}}` dari `team_info`; dengan `--compare` mencetak selisih spend per team

- [ ] **Step 1: Tulis smoke test**

```python
@pytest.mark.parametrize("model", ["company-coding", "company-reasoning"])
def test_t06_streaming(model):
    # SMOKE_KEY, stream=True, prompt "count from 1 to 20"
    assert chunks >= 5 and first_token_seconds < 30

@pytest.mark.parametrize("model", ["company-coding", "company-reasoning"])
def test_t07_tool_calling(model):
    # tool get_current_time tanpa parameter, prompt "What time is it? Use the tool."
    assert tool_calls[0]["function"]["name"] == "get_current_time"
```

Test di-skip dengan pesan jelas bila `SMOKE_KEY` tidak diisi.

- [ ] **Step 2: Verifikasi lokal**

Run: `make smoke SMOKE_KEY=$(make -s ctl ARGS='key issue --user dev1@local.test --label smoke')`, atau terbitkan key dulu lalu `make smoke SMOKE_KEY=sk-...`
Expected: T06 PASS terhadap mock. T07 PASS untuk tool call tanpa stream. Uji yang sebenarnya dijalankan di VM sesuai checklist.

- [ ] **Step 3: Tulis entitlement pilot dan dokumentasi**

- `entitlements/pilot.yaml`: team `it-developer` dan `finance` dengan nilai dari matriks panduan 4.1, satu `smoke@perusahaan.com` di `it-developer` dengan key 30d $2, dan member lain dikomentari sebagai tempat isian.
- `docs/opencode.example.json`: format panduan 5.5 dengan model `company-coding` dan `company-reasoning`. Cek dokumentasi OpenCode (context7) untuk pengaturan retry client. Bila ada, set ke minimum; bila tidak ada, nyatakan itu di onboarding.
- `docs/onboarding.md`: menyimpan key di `COMPANY_LLM_KEY`, memasang template, dan tabel error (401 key tidak valid/diblokir, error akses model, 429 rate limit atau budget habis, 5xx masalah upstream).
- `docs/pilot-checklist.md`: konfirmasi Gate 1 (nilai sementara spec bagian 10); langkah deploy VM (`vm.env`, sertifikat di `deploy/certs/`, `make up ENV=vm`, `make plan/apply ENV=vm`, `key issue` untuk smoke); T06/T07 manual (sesi OpenCode ≥ 10 menit di kedua alias, tugas agent yang mengedit file); prosedur T11 (`spend_report.py` sebelum dan sesudah smoke, bandingkan dengan dashboard usage OpenAI Project, selisih < 5%); tempat mencatat hasil T03 dan T05.

- [ ] **Step 4: Validasi**

Run: `make plan FILE=entitlements/pilot.yaml` terhadap stack lokal
Expected: exit 2 dengan rencana pembuatan team pilot dan tanpa error validasi. Tidak di-apply.

- [ ] **Step 5: Commit** — `git commit -m "feat: smoke tests, pilot entitlements, and onboarding docs"`
