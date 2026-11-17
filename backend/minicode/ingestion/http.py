"""Shared HTTP plumbing for the Graph and Speech REST clients.

* Bearer tokens come from a `TokenProvider` (azure-identity in Azure, a static token in tests).
* Transient failures (429 / 5xx / network) are retried, honouring `Retry-After` (Graph throttling).
* The httpx transport is injectable, which is how tests and the local mock services plug in.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class TokenProvider(Protocol):
    def get_token(self) -> str: ...


class StaticTokenProvider:
    def __init__(self, token: str = "test-token") -> None:
        self.token = token

    def get_token(self) -> str:
        return self.token


class AzureIdentityTokenProvider:
    """Wraps an azure-identity credential (DefaultAzureCredential, certificate, MI) for one scope.

    azure-identity caches tokens and refreshes them before expiry, so calling it per request is fine.
    """

    def __init__(self, scope: str, credential: Any | None = None) -> None:
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self.credential = credential
        self.scope = scope

    def get_token(self) -> str:
        return self.credential.get_token(self.scope).token


class HttpError(RuntimeError):
    def __init__(self, response: httpx.Response) -> None:
        self.status_code = response.status_code
        self.body = response.text[:2000]
        super().__init__(f"{response.request.method} {response.request.url} -> {response.status_code}: {self.body[:300]}")


class RestClient:
    def __init__(
        self,
        base_url: str,
        tokens: TokenProvider | None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.tokens = tokens
        self.max_retries = max_retries
        self.sleep = sleep
        self.http = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)

    def url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    def request(self, method: str, path_or_url: str, *, auth: bool = True, **kwargs: Any) -> httpx.Response:
        url = self.url(path_or_url)
        headers = dict(kwargs.pop("headers", None) or {})
        if auth and self.tokens is not None:
            headers["Authorization"] = f"Bearer {self.tokens.get_token()}"
        attempt = 0
        while True:
            try:
                response = self.http.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError:
                if attempt >= self.max_retries:
                    raise
                self.sleep(min(2**attempt, 30))
                attempt += 1
                continue
            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                self.sleep(_retry_after(response, attempt))
                attempt += 1
                continue
            if response.status_code >= 400:
                raise HttpError(response)
            return response

    def get_json(self, path_or_url: str, **kwargs: Any) -> Any:
        return self.request("GET", path_or_url, **kwargs).json()


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("Retry-After")
    if value:
        try:
            return min(float(value), 120.0)
        except ValueError:
            pass
    return float(min(2**attempt, 30))
