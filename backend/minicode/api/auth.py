"""Entra ID bearer-token validation for the Search API.

Tokens are access tokens issued for the backend API app registration (audience `api://<client-id>`
or `<client-id>`), signed RS256 with keys from the tenant's JWKS endpoint. Checked: signature, exp/nbf
(with leeway), audience, issuer (v2 or v1 for this tenant), tid. Authorization:
- read endpoints: delegated scope `Learning.Read` (SPA users) or an app role (`Learning.Read` / admin role)
- admin endpoints: app role `Learning.Admin` in the `roles` claim

AUTH_MODE=dev skips token validation and returns a fixed principal. It is refused when
MINICODE_ENVIRONMENT is prod, and logged loudly otherwise.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import jwt

log = logging.getLogger(__name__)
PROD_ENVIRONMENTS = {"prod", "production"}


class AuthError(Exception):
    def __init__(self, status: int, message: str, code: str = "invalid_token") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code

    @property
    def www_authenticate(self) -> str:
        return f'Bearer error="{self.code}", error_description="{self.message}"'


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str | None
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    tenant_id: str | None = None
    is_dev: bool = False
    claims: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    @property
    def display(self) -> str:
        return self.name or self.user_id


class Authenticator(Protocol):
    admin_role: str

    def authenticate(self, headers: Mapping[str, str]) -> Principal: ...

    def require(self, headers: Mapping[str, str], admin: bool = False) -> Principal: ...


def bearer_token(headers: Mapping[str, str]) -> str:
    value = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(401, "missing bearer token", "invalid_request")
    return token.strip()


class JwksCache:
    def __init__(self, url: str, transport: httpx.BaseTransport | None = None, ttl: float = 3600, min_refresh: float = 300,
                 clock=time.monotonic) -> None:  # noqa: ANN001
        self.url = url
        self.http = httpx.Client(transport=transport, timeout=10.0)
        self.ttl = ttl
        self.min_refresh = min_refresh
        self.clock = clock
        self._keys: dict[str, Any] = {}
        self._fetched = float("-inf")
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        resp = self.http.get(self.url)
        resp.raise_for_status()
        keys = {}
        for k in resp.json().get("keys", []):
            if k.get("kty") == "RSA" and k.get("kid") and k.get("use", "sig") == "sig":
                keys[k["kid"]] = jwt.PyJWK(k, algorithm="RS256").key
        self._keys, self._fetched = keys, self.clock()

    def get(self, kid: str) -> Any:
        with self._lock:
            age = self.clock() - self._fetched
            if age > self.ttl or (kid not in self._keys and age > self.min_refresh):
                try:
                    self._refresh()  # key rollover: unknown kid triggers a (rate-limited) refresh
                except httpx.HTTPError as e:
                    if not self._keys:
                        raise AuthError(503, f"signing keys unavailable: {e}", "temporarily_unavailable") from e
                    log.warning("JWKS refresh failed, using cached keys: %s", e)
            if kid not in self._keys:
                raise AuthError(401, "unknown signing key")
            return self._keys[kid]


class EntraAuthenticator:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        admin_role: str = "Learning.Admin",
        read_scope: str = "Learning.Read",
        transport: httpx.BaseTransport | None = None,
        leeway: int = 120,
        authority: str = "https://login.microsoftonline.com",
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.admin_role = admin_role
        self.read_scope = read_scope
        self.leeway = leeway
        self.audiences = [f"api://{client_id}", client_id]
        self.issuers = {f"{authority}/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"}
        self.jwks = JwksCache(f"{authority}/{tenant_id}/discovery/v2.0/keys", transport)

    def validate(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise AuthError(401, "malformed token") from e
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise AuthError(401, "unsupported token algorithm")
        key = self.jwks.get(header["kid"])
        try:
            claims = jwt.decode(
                token, key, algorithms=["RS256"], audience=self.audiences, leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthError(401, "token expired") from e
        except jwt.InvalidAudienceError as e:
            raise AuthError(401, "invalid audience") from e
        except jwt.PyJWTError as e:
            raise AuthError(401, f"invalid token: {type(e).__name__}") from e
        if claims.get("iss") not in self.issuers:
            raise AuthError(401, "invalid issuer")
        if claims.get("tid") and claims["tid"] != self.tenant_id:
            raise AuthError(401, "token from another tenant")
        return claims

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        claims = self.validate(bearer_token(headers))
        return Principal(
            user_id=claims.get("oid") or claims.get("sub", ""),
            name=claims.get("preferred_username") or claims.get("name") or claims.get("upn"),
            roles=tuple(claims.get("roles") or ()),
            scopes=tuple((claims.get("scp") or "").split()),
            tenant_id=claims.get("tid"),
            claims=claims,
        )

    def require(self, headers: Mapping[str, str], admin: bool = False) -> Principal:
        return authorize(self.authenticate(headers), admin, self.admin_role, self.read_scope)


def authorize(p: Principal, admin: bool, admin_role: str, read_scope: str) -> Principal:
    if admin:
        if admin_role not in p.roles:
            raise AuthError(403, f"requires app role {admin_role}", "insufficient_scope")
    elif read_scope not in p.scopes and read_scope not in p.roles and admin_role not in p.roles:
        raise AuthError(403, f"requires scope or role {read_scope}", "insufficient_scope")
    return p


class DevAuthenticator:
    """Local development only: no token needed. `X-Dev-Roles: none` simulates a non-admin user."""

    def __init__(self, user: str = "dev.user@localhost", roles: tuple[str, ...] = ("Learning.Admin",),
                 admin_role: str = "Learning.Admin", read_scope: str = "Learning.Read") -> None:
        self.user = user
        self.roles = roles
        self.admin_role = admin_role
        self.read_scope = read_scope

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        lower = {k.lower(): v for k, v in headers.items()}
        roles = self.roles
        if "x-dev-roles" in lower:
            roles = tuple(r.strip() for r in lower["x-dev-roles"].split(",") if r.strip() and r.strip() != "none")
        return Principal(user_id=self.user, name=self.user, roles=roles, scopes=(self.read_scope,), is_dev=True)

    def require(self, headers: Mapping[str, str], admin: bool = False) -> Principal:
        return authorize(self.authenticate(headers), admin, self.admin_role, self.read_scope)


def build_authenticator(settings: Any, transport: httpx.BaseTransport | None = None) -> Authenticator:
    if settings.auth_mode == "dev":
        if settings.environment.lower() in PROD_ENVIRONMENTS:
            raise RuntimeError("AUTH_MODE=dev is not allowed when MINICODE_ENVIRONMENT=prod")
        log.warning("AUTH_MODE=dev: API authentication is DISABLED (environment=%s)", settings.environment)
        return DevAuthenticator(settings.dev_user, settings.dev_roles, settings.admin_role, settings.read_scope)
    if settings.auth_mode == "entra":
        if not settings.tenant_id or not settings.api_client_id:
            raise RuntimeError("AUTH_MODE=entra needs AUTH_TENANT_ID and API_CLIENT_ID")
        return EntraAuthenticator(settings.tenant_id, settings.api_client_id, settings.admin_role, settings.read_scope,
                                  transport)
    raise RuntimeError(f"unknown AUTH_MODE {settings.auth_mode!r} (entra | dev)")
