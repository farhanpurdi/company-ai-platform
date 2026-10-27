TOOLS_IMAGE := llm-gateway-tools

# Profile: local (mock upstream) or vm (real OpenAI).
ENV ?= local
COMPOSE = docker compose -p llm-gateway-$(ENV) -f deploy/compose.yaml -f deploy/compose.$(ENV).yaml --env-file deploy/env/$(ENV).env

# Entitlements file per profile; override with FILE=...
FILE_local := entitlements/local.yaml
FILE_vm := entitlements/pilot.yaml
FILE ?= $(FILE_$(ENV))
OPERATOR ?= $(shell git config user.email)
GIT_SHA = $(shell git log -1 --format=%H -- $(FILE))

# -T keeps stdout (raw key from `key issue`) separate from stderr (everything else).
CTL = $(COMPOSE) run --rm -T -e GATEWAYCTL_OPERATOR="$(OPERATOR)" -e GATEWAYCTL_GIT_SHA="$(GIT_SHA)" tools gatewayctl --file $(FILE)

.PHONY: tools-build unit init-local up down ps logs config plan apply ctl test

# Image with gatewayctl, pytest and the test dependencies.
tools-build:
	docker build -f tools/Dockerfile -t $(TOOLS_IMAGE) .

# Unit tests need no stack; the repo is mounted at /repo. No pytest cache: the
# container runs as root and would leave root-owned files in the checkout.
unit: tools-build
	docker run --rm -v "$(CURDIR):/repo" -w /repo $(TOOLS_IMAGE) pytest -p no:cacheprovider gatewayctl/tests mock_upstream/tests deploy/tests -q

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

# Needs the local stack (make up). Test dirs that do not exist yet are skipped;
# the T10 log scan runs once scripts/t10-scan-logs.sh exists.
test:
	$(COMPOSE) run --rm -T tools pytest -p no:cacheprovider $(wildcard tests/integration tests/acceptance) -v
	@if [ -f scripts/t10-scan-logs.sh ]; then scripts/t10-scan-logs.sh $(ENV); else echo "scripts/t10-scan-logs.sh belum ada; scan log T10 dilewati"; fi
