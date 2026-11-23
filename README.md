# LiteLLM Pilot Gateway

Gateway LLM internal berbasis LiteLLM Proxy (pilot Fase 0–1): virtual key per user, budget dan rate limit per team, alias model `company-fast`, `company-coding`, dan `company-reasoning`, serta provisioning deklaratif lewat `gatewayctl`.

Mulai cepat (host hanya butuh Docker dan `make`):

```sh
make hooks && make init-local   # sekali per clone
make up && make apply           # nyalakan stack lokal (mock upstream) dan terapkan entitlements
make test                       # unit, integrasi, dan acceptance
```

| Dokumen | Untuk |
| --- | --- |
| `docs/panduan/setup-admin.md` | **Mulai di sini:** langkah demi langkah setup lokal, VM, dan tugas admin |
| `docs/panduan/operator-guide.md` | Referensi: menyalakan stack, mencoba request, operasi harian, troubleshooting |
| `docs/fase-0-1-pilot/pilot-checklist.md` | Deploy VM, smoke T06/T07, rekonsiliasi T11, catatan Gate 2 |
| `docs/panduan/onboarding.md` | Pengguna akhir: menyimpan key, OpenCode, arti error |
| `docs/fase-0-1-pilot/spec.md` | Spec desain |
