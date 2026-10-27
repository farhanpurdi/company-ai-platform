TOOLS_IMAGE := llm-gateway-tools

# Profile: local (mock upstream) or vm (real OpenAI).
ENV ?= local
COMPOSE = docker compose -p llm-gateway-$(ENV) -f deploy/compose.yaml -f deploy/compose.$(ENV).yaml --env-file deploy/env/$(ENV).env

.PHONY: tools-build unit init-local up down ps logs config

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
