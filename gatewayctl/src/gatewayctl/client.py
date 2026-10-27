"""HTTP client for the LiteLLM management API, with secret redaction."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import httpx

PAGE_SIZE = 100
_RAW_KEY = re.compile(r"sk-[A-Za-z0-9_-]{6,}")


class GatewayUnavailable(Exception):
    """LiteLLM is unreachable or rejected the master key.

    may_have_applied is True when the request may already have reached LiteLLM
    (e.g. a read timeout), so a mutating call cannot be assumed to have failed.
    """

    def __init__(self, message: str, *, may_have_applied: bool = False) -> None:
        super().__init__(message)
        self.may_have_applied = may_have_applied


# Raised before the request is written, so the server never saw it.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)


def _invalid_url() -> GatewayUnavailable:
    return GatewayUnavailable("URL LiteLLM tidak valid; periksa --base-url atau LITELLM_BASE_URL")


class ApiError(Exception):
    def __init__(self, status: int, path: str, detail: str):
        super().__init__(f"{path} -> HTTP {status}: {detail}")
        self.status = status
        self.path = path
        self.detail = detail


def redact(text: str, secrets: Iterable[str]) -> str:
    # Longest first so a secret that contains another one is replaced whole.
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "sk-***")
    return _RAW_KEY.sub("sk-***", text)


class LiteLLMClient:
    def __init__(
        self,
        base_url: str,
        master_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        self._master_key = master_key
        try:
            self._http = httpx.Client(
                base_url=base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {master_key}"},
                transport=transport,
                timeout=timeout,
            )
        except httpx.InvalidURL:
            raise _invalid_url() from None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LiteLLMClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _redact(self, text: str) -> str:
        return redact(text, [self._master_key])

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.InvalidURL:
            raise _invalid_url() from None
        except httpx.TransportError as exc:
            # Only the exception class: its text may echo URLs or headers.
            raise GatewayUnavailable(
                f"tidak dapat menghubungi LiteLLM ({type(exc).__name__})",
                may_have_applied=not isinstance(exc, _NOT_SENT),
            ) from None
        if response.status_code >= 400:
            raise ApiError(response.status_code, path, self._redact(response.text))
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        return response.json() if response.content else {}

    def check(self) -> None:
        try:
            self._request("GET", "/key/list", params={"size": 1})
        except ApiError as exc:
            if exc.status in (401, 403):
                raise GatewayUnavailable("master key ditolak oleh LiteLLM") from None
            raise

    def list_teams(self) -> list[dict]:
        return self._json("GET", "/team/list")

    def team_info(self, team_id: str) -> dict:
        return self._json("GET", "/team/info", params={"team_id": team_id})

    def list_keys(self) -> list[dict]:
        keys: list[dict] = []
        page = 1
        while True:
            data = self._json(
                "GET",
                "/key/list",
                params={"return_full_object": "true", "page": page, "size": PAGE_SIZE},
            )
            batch = data.get("keys") or []
            keys.extend(batch)
            total_pages = data.get("total_pages")
            if total_pages is not None:
                if page >= total_pages:
                    break
            elif len(batch) < PAGE_SIZE:
                break
            if not batch:
                break
            page += 1
        return keys

    def key_info(self, key: str) -> dict:
        return self._json("GET", "/key/info", params={"key": key})

    def team_new(self, payload: dict) -> dict:
        return self._json("POST", "/team/new", json=payload)

    def team_update(self, payload: dict) -> dict:
        return self._json("POST", "/team/update", json=payload)

    def team_delete(self, team_id: str) -> None:
        self._request("POST", "/team/delete", json={"team_ids": [team_id]})

    def member_add(self, team_id: str, user_id: str, max_budget_in_team: float | None) -> None:
        payload: dict[str, Any] = {"team_id": team_id, "member": {"user_id": user_id, "role": "user"}}
        if max_budget_in_team is not None:
            payload["max_budget_in_team"] = max_budget_in_team
        self._request("POST", "/team/member_add", json=payload)

    def member_update(self, team_id: str, user_id: str, max_budget_in_team: float | None) -> None:
        self._request(
            "POST",
            "/team/member_update",
            json={"team_id": team_id, "user_id": user_id, "max_budget_in_team": max_budget_in_team},
        )

    def member_delete(self, team_id: str, user_id: str) -> None:
        self._request("POST", "/team/member_delete", json={"team_id": team_id, "user_id": user_id})

    def key_generate(self, payload: dict) -> dict:
        return self._json("POST", "/key/generate", json=payload)

    def key_update(self, payload: dict) -> None:
        self._request("POST", "/key/update", json=payload)

    def key_block(self, token: str) -> None:
        self._request("POST", "/key/block", json={"key": token})
