TOOLS_IMAGE := llm-gateway-tools

.PHONY: tools-build unit

# Image with gatewayctl, pytest and the test dependencies.
tools-build:
	docker build -f tools/Dockerfile -t $(TOOLS_IMAGE) .

# Unit tests need no stack; the repo is mounted at /repo. No pytest cache: the
# container runs as root and would leave root-owned files in the checkout.
unit: tools-build
	docker run --rm -v "$(CURDIR):/repo" -w /repo $(TOOLS_IMAGE) pytest -p no:cacheprovider gatewayctl/tests mock_upstream/tests -q
