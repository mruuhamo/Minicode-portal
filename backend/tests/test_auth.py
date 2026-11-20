from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from minicode.api.auth import AuthError, DevAuthenticator, EntraAuthenticator, build_authenticator

TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
ISS = f"https://login.microsoftonline.com/{TENANT}/v2.0"


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks_calls() -> list[str]:
    return []


@pytest.fixture
def auth(key, jwks_calls) -> EntraAuthenticator:  # noqa: ANN001
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))

    def handler(r: httpx.Request) -> httpx.Response:
        jwks_calls.append(str(r.url))
        return httpx.Response(200, json={"keys": [{**jwk, "kid": "k1", "use": "sig"}]})

    return EntraAuthenticator(TENANT, CLIENT, transport=httpx.MockTransport(handler))


def token(key, kid: str = "k1", alg: str = "RS256", **overrides: Any) -> str:  # noqa: ANN001
    now = int(time.time())
    claims = {"iss": ISS, "aud": f"api://{CLIENT}", "tid": TENANT, "oid": "user-1", "preferred_username": "aino@contoso.com",
              "scp": "Learning.Read", "iat": now, "nbf": now, "exp": now + 3600, **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    signing_key = "shared-secret-long-enough-for-hs256!!" if alg == "HS256" else key
    return jwt.encode(claims, signing_key, algorithm=alg, headers={"kid": kid})


def bearer(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def test_valid_token_yields_principal(auth, key, jwks_calls) -> None:  # noqa: ANN001
    p = auth.require(bearer(token(key)))
    assert p.user_id == "user-1" and p.display == "aino@contoso.com" and p.scopes == ("Learning.Read",)
    auth.require(bearer(token(key, aud=CLIENT)))  # bare client-id audience
    auth.require(bearer(token(key, iss=f"https://sts.windows.net/{TENANT}/")))  # v1 issuer
    assert jwks_calls == [f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"]  # cached


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"exp": int(time.time()) - 3600}, "expired"),
        ({"aud": "api://someone-else"}, "audience"),
        ({"iss": "https://login.microsoftonline.com/other/v2.0"}, "issuer"),
        ({"tid": "33333333-3333-3333-3333-333333333333"}, "tenant"),
        ({"exp": None}, "invalid token"),
    ],
)
def test_rejected_claims(auth, key, overrides, message) -> None:  # noqa: ANN001
    with pytest.raises(AuthError) as e:
        auth.require(bearer(token(key, **overrides)))
    assert e.value.status == 401 and message in e.value.message


def test_rejects_bad_signature_alg_kid_and_missing_header(auth, key) -> None:  # noqa: ANN001
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cases = [token(other), token(key, alg="HS256"), token(key, kid="unknown"), "not-a-jwt"]
    for t in cases:
        with pytest.raises(AuthError) as e:
            auth.require(bearer(t))
        assert e.value.status == 401
    with pytest.raises(AuthError) as e:
        auth.require({})
    assert e.value.status == 401 and "Bearer" in e.value.www_authenticate


def test_scope_and_admin_role(auth, key) -> None:  # noqa: ANN001
    with pytest.raises(AuthError) as e:
        auth.require(bearer(token(key)), admin=True)
    assert e.value.status == 403
    with pytest.raises(AuthError) as e:
        auth.require(bearer(token(key, scp="User.Read")))
    assert e.value.status == 403
    admin = auth.require(bearer(token(key, scp=None, roles=["Learning.Admin"])), admin=True)
    assert "Learning.Admin" in admin.roles
    auth.require(bearer(token(key, scp=None, roles=["Learning.Read"])))  # app-only read client


def test_jwks_unavailable_is_503() -> None:
    a = EntraAuthenticator(TENANT, CLIENT, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthError) as e:
        a.require(bearer(token(key)))
    assert e.value.status == 503


def test_dev_authenticator_roles_header() -> None:
    dev = DevAuthenticator()
    assert dev.require({}, admin=True).is_dev
    with pytest.raises(AuthError) as e:
        dev.require({"X-Dev-Roles": "none"}, admin=True)
    assert e.value.status == 403
    assert dev.require({"x-dev-roles": "none"}).roles == ()


def _settings(**kw: Any) -> SimpleNamespace:
    base = dict(auth_mode="dev", environment="dev", dev_user="u", dev_roles=("Learning.Admin",), admin_role="Learning.Admin",
                read_scope="Learning.Read", tenant_id="", api_client_id="")
    return SimpleNamespace(**{**base, **kw})


def test_build_authenticator_guards() -> None:
    assert isinstance(build_authenticator(_settings()), DevAuthenticator)
    for env in ("prod", "Production"):
        with pytest.raises(RuntimeError, match="not allowed"):
            build_authenticator(_settings(environment=env))
    with pytest.raises(RuntimeError, match="AUTH_TENANT_ID"):
        build_authenticator(_settings(auth_mode="entra"))
    assert isinstance(build_authenticator(_settings(auth_mode="entra", tenant_id=TENANT, api_client_id=CLIENT)), EntraAuthenticator)
    with pytest.raises(RuntimeError, match="unknown"):
        build_authenticator(_settings(auth_mode="none"))
