TOOLS_IMAGE := llm-gateway-tools

# Profile: local (mock upstream) or vm (real OpenAI).
ENV ?= local
COMPOSE = docker compose -p llm-gateway-$(ENV) -f deploy/compose.yaml -f deploy/compose.$(ENV).yaml --env-file deploy/env/$(ENV).env

# Entitlements file per profile; override with FILE=...
FILE_local := entitlements/local.yaml
FILE_vm := entitlements/pilot.yaml
FILE ?= $(FILE_$(ENV))
OPERATOR ?= $(shell git config user.email)
# Last commit of FILE; "-dirty" when the applied file differs from that commit.
GIT_SHA = $(shell sha=$$(git log -1 --format=%H -- $(FILE)); \
	if [ -n "$$(git status --porcelain -- $(FILE))" ]; then echo "$${sha:-untracked}-dirty"; else echo "$$sha"; fi)

# The tools container runs as the host user (compose.yaml), so files it writes
# to the checkout (var/audit.log, var/t10-sentinels.txt) stay host-owned.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)

# -T keeps stdout (raw key from `key issue`) separate from stderr (everything else).
CTL = $(COMPOSE) run --rm -T -e GATEWAYCTL_OPERATOR="$(OPERATOR)" -e GATEWAYCTL_GIT_SHA="$(GIT_SHA)" tools gatewayctl --file $(FILE)

.PHONY: tools-build unit init-local up down ps logs config plan apply ctl local-ca vm-ca test smoke hooks

# Enable the versioned pre-commit hook in .githooks (secret, path, syntax and unit checks).
hooks:
	git config core.hooksPath .githooks

# Image with gatewayctl, pytest and the test dependencies.
tools-build:
	docker build -f tools/Dockerfile -t $(TOOLS_IMAGE) .

# Unit tests need no stack; the repo is mounted at /repo. No pytest cache: it
# would only add clutter to the checkout.
unit: tools-build
	docker run --rm --user $(HOST_UID):$(HOST_GID) -v "$(CURDIR):/repo" -w /repo $(TOOLS_IMAGE) pytest -p no:cacheprovider gatewayctl/tests mock_upstream/tests deploy/tests -q

# Random local secrets; refuses to overwrite an existing deploy/env/local.env.
init-local:
	sh scripts/init-local.sh

up:
	$(COMPOSE) up -d --build --wait --wait-timeout 300

# Keeps volumes: keys, teams and spend live in them.
down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

# make logs ARGS='-f litellm-a'
logs:
	$(COMPOSE) logs $(ARGS)

# Validate only (-q): the rendered config would contain secrets.
config:
	$(COMPOSE) config -q

# Recipes that run gatewayctl are silent (@): make's own command echo would go
# to stdout and corrupt KEY=$(make ctl ARGS='key issue ...').

# make plan [ARGS=--json]; exit 2 means there are changes.
plan:
	@$(CTL) plan $(ARGS)

# make apply [ARGS='--confirm --prune']
apply:
	@$(CTL) apply $(ARGS)

# make ctl ARGS='key issue --user U --label L' (also key block/list)
ctl:
	@$(CTL) $(ARGS)

# Local profile: Caddy's internal CA sits in a root-only volume the tools
# container (host user) cannot read; the certificate is public, so copy it out.
LOCAL_CA := var/caddy-local-root.crt
local-ca:
ifeq ($(ENV),local)
	@mkdir -p var
	@$(COMPOSE) exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > $(LOCAL_CA).tmp
	@mv $(LOCAL_CA).tmp $(LOCAL_CA)
endif

# VM with VM_TLS=internal (access by IP): Caddy's root certificate for the tools
# container (GATEWAY_CA_BUNDLE in vm.env) and for tester laptops. Also public.
VM_CA := var/caddy-vm-root.crt
vm-ca:
	@[ "$(ENV)" = vm ] || { echo "vm-ca hanya untuk ENV=vm" >&2; exit 1; }
	@mkdir -p var
	@$(COMPOSE) exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > $(VM_CA).tmp
	@mv $(VM_CA).tmp $(VM_CA)

# Unit, then integration and acceptance against the local stack (make up),
# then the T10 log scan on the host.
test: unit local-ca
	$(COMPOSE) run --rm -T tools pytest -p no:cacheprovider tests/integration tests/acceptance -v
	scripts/t10-scan-logs.sh $(ENV)

# Smoke T06/T07 through the gateway. SMOKE_KEY is a virtual key from `make ctl
# ARGS='key issue ...'`, read from the environment: `SMOKE_KEY="$$SMOKE_KEY" make
# smoke ENV=vm`. Never pass it as a make argument: argv is visible in `ps`.
# Intended for ENV=vm (real OpenAI).
smoke: local-ca
	$(COMPOSE) run --rm -T -e SMOKE_KEY tools pytest -p no:cacheprovider tests/smoke -v
