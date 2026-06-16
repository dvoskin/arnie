"""
Tests for `api.auth.verify_apple_identity_token`.

Signs a real RS256 JWT with a freshly generated keypair and monkey-patches the
module's JWKS lookup to return the matching public key, so the verification path
is exercised end-to-end without hitting Apple's servers.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from api import auth as api_auth


@pytest.fixture
def signing_key():
    """A fresh RSA keypair per test (2048-bit is plenty for unit tests)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def stub_jwks(monkeypatch, signing_key):
    """Replace `PyJWKClient` in api.auth so `get_signing_key_from_jwt` returns our
    test public key for any kid. Also clears the lazy module-level client cache
    so each test gets a fresh fake."""
    public_key = signing_key.public_key()

    class FakeJWKSClient:
        def __init__(self, url):  # noqa: D401 – signature must match PyJWKClient
            pass

        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=public_key)

    monkeypatch.setattr(api_auth, "PyJWKClient", FakeJWKSClient)
    monkeypatch.setattr(api_auth, "_apple_jwks_client", None)
    monkeypatch.setenv("APPLE_SIWA_CLIENT_ID", "com.tryarnie.app")


def _make_token(signing_key, **claim_overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": "com.tryarnie.app",
        "sub": "001234.abcdef.123",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(claim_overrides)
    pem = signing_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "test-key"})


def test_verify_returns_namespaced_apple_subject(signing_key):
    token = _make_token(signing_key)
    assert api_auth.verify_apple_identity_token(token) == "apple:001234.abcdef.123"


@pytest.mark.parametrize("bad_token", ["", "   ", "\n"])
def test_empty_token_raises_400(bad_token):
    with pytest.raises(HTTPException) as exc:
        api_auth.verify_apple_identity_token(bad_token)
    assert exc.value.status_code == 400


def test_wrong_audience_raises_401(signing_key):
    token = _make_token(signing_key, aud="com.someoneelse.app")
    with pytest.raises(HTTPException) as exc:
        api_auth.verify_apple_identity_token(token)
    assert exc.value.status_code == 401


def test_wrong_issuer_raises_401(signing_key):
    token = _make_token(signing_key, iss="https://evil.example.com")
    with pytest.raises(HTTPException) as exc:
        api_auth.verify_apple_identity_token(token)
    assert exc.value.status_code == 401


def test_expired_token_raises_401(signing_key):
    token = _make_token(signing_key, exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc:
        api_auth.verify_apple_identity_token(token)
    assert exc.value.status_code == 401


def test_missing_subject_raises_401(signing_key):
    token = _make_token(signing_key, sub="")
    with pytest.raises(HTTPException) as exc:
        api_auth.verify_apple_identity_token(token)
    assert exc.value.status_code == 401


def test_tampered_token_raises_401(signing_key):
    """Flip a character in the payload — signature won't match → 401."""
    token = _make_token(signing_key)
    header, payload, sig = token.split(".")
    tampered = f"{header}.{payload[:-1]}X.{sig}" if payload else token
    with pytest.raises(HTTPException) as exc:
        api_auth.verify_apple_identity_token(tampered)
    assert exc.value.status_code == 401


def test_audience_can_be_overridden_via_env(signing_key, monkeypatch):
    """If APPLE_SIWA_CLIENT_ID is set (e.g., for a web Services ID), it's honored."""
    monkeypatch.setenv("APPLE_SIWA_CLIENT_ID", "com.tryarnie.web")
    token = _make_token(signing_key, aud="com.tryarnie.web")
    assert api_auth.verify_apple_identity_token(token) == "apple:001234.abcdef.123"


def test_provider_dispatch_routes_apple_through_verifier(signing_key):
    """`verify_provider_credential('apple', token)` should reach the JWT verifier."""
    token = _make_token(signing_key)
    assert api_auth.verify_provider_credential("apple", token) == "apple:001234.abcdef.123"
