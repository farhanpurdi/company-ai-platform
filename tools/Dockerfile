FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Editable install: the repo mounted at /repo at runtime overrides this copy.
COPY gatewayctl /repo/gatewayctl
RUN pip install -e "/repo/gatewayctl[test]"

WORKDIR /repo
