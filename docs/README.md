# Dokumentasi LiteLLM Pilot Gateway

Dokumen dikelompokkan per tahap. Tahap sekarang: Fase 2 selesai di sisi kode (PR #19); Gate 3 menunggu eksekusi di VM dan konfirmasi DevOps (`fase-2-vm-production/gate3-checklist.md`).

## panduan/ — dokumen hidup untuk operator dan pengguna

| Dokumen | Untuk |
| --- | --- |
| `setup-admin.md` | **Mulai di sini:** setup lokal, VM, dan tugas admin |
| `operator-guide.md` | Menyalakan stack, operasi harian, troubleshooting |
| `onboarding.md` | Pengguna akhir: menyimpan key, OpenCode, arti error |
| `opencode.example.json` | Contoh konfigurasi OpenCode |

## referensi/ — konteks lintas fase

| Dokumen | Untuk |
| --- | --- |
| `LITELLM_IMPLEMENTATION_GUIDE.md` | Fase, gate, dan daftar uji |
| `LLM_GATEWAY_ARCHITECTURE.md` | Arsitektur gateway |

## fase-0-1-pilot/ — pilot (Gate 1 dan 2, selesai)

`spec.md`, `plan.md`, `remove-caddy-plan.md`, `remove-caddy-goal.md`, `pilot-checklist.md` (deploy VM, smoke, hasil Gate 2).

## fase-2-vm-production/ — produksi di VM (Gate 3, berjalan)

`spec.md`, `plan.md`, `goal.md`, `gate3-checklist.md` (tabel hasil T12–T16), `devops-handoff.md` (pembagian tugas dengan DevOps).
