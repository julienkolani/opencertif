from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from core import auth
from core import config as config_module


def _generate_rsa_pem_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


@pytest.fixture
def rsa_keypair():
    return _generate_rsa_pem_pair()


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_URL", "https://auth.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "opencertif")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "opencertif-api")
    monkeypatch.setenv("DEV_MODE", "false")
    config_module.get_settings.cache_clear()
    yield config_module.get_settings()
    config_module.get_settings.cache_clear()


def _make_token(private_pem, settings, roles, exp_delta=timedelta(minutes=5), issuer=None):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "user-123",
        "preferred_username": "julien",
        "iss": issuer or f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}",
        "iat": now,
        "exp": now + exp_delta,
        "realm_access": {"roles": roles},
    }
    return jose_jwt.encode(claims, private_pem, algorithm="RS256")


# --- get_user_roles ---


def test_get_user_roles_extracts_realm_roles():
    claims = {"realm_access": {"roles": ["certifs-admin", "certifs-viewer"]}}
    assert auth.get_user_roles(claims) == ["certifs-admin", "certifs-viewer"]


def test_get_user_roles_missing_defaults_to_empty():
    assert auth.get_user_roles({}) == []


# --- verify_token ---


def test_verify_token_valid(monkeypatch, settings, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setattr(auth, "get_keycloak_public_key", lambda s: public_pem)
    token = _make_token(private_pem, settings, roles=["certifs-admin"])

    claims = auth.verify_token(token, settings)

    assert claims["sub"] == "user-123"
    assert claims["realm_access"]["roles"] == ["certifs-admin"]


def test_verify_token_expired_raises(monkeypatch, settings, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setattr(auth, "get_keycloak_public_key", lambda s: public_pem)
    token = _make_token(
        private_pem, settings, roles=["certifs-admin"], exp_delta=timedelta(minutes=-5)
    )

    with pytest.raises(auth.JWTError):
        auth.verify_token(token, settings)


def test_verify_token_wrong_issuer_raises(monkeypatch, settings, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setattr(auth, "get_keycloak_public_key", lambda s: public_pem)
    token = _make_token(
        private_pem, settings, roles=["certifs-admin"], issuer="https://evil.example.com/realms/other"
    )

    with pytest.raises(auth.JWTError):
        auth.verify_token(token, settings)


def test_verify_token_bad_signature_raises(monkeypatch, settings, rsa_keypair):
    _, public_pem = rsa_keypair
    other_private_pem, _ = _generate_rsa_pem_pair()
    monkeypatch.setattr(auth, "get_keycloak_public_key", lambda s: public_pem)
    token = _make_token(other_private_pem, settings, roles=["certifs-admin"])

    with pytest.raises(auth.JWTError):
        auth.verify_token(token, settings)


# --- require_role (FastAPI dependency) ---


def _build_app(role: str) -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    def protected(user: dict = Depends(auth.require_role(role))):
        return {"sub": user.get("sub")}

    return app


def test_require_role_dev_mode_bypasses_auth(monkeypatch):
    monkeypatch.setenv("DEV_MODE", "true")
    config_module.get_settings.cache_clear()
    try:
        client = TestClient(_build_app("certifs-admin"))
        response = client.get("/protected")

        assert response.status_code == 200
        assert response.json()["sub"] == "dev-user"
    finally:
        config_module.get_settings.cache_clear()


def test_require_role_missing_header_returns_401(settings):
    client = TestClient(_build_app("certifs-admin"))

    response = client.get("/protected")

    assert response.status_code == 401


def test_require_role_wrong_role_returns_403(monkeypatch, settings, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setattr(auth, "get_keycloak_public_key", lambda s: public_pem)
    token = _make_token(private_pem, settings, roles=["certifs-viewer"])

    client = TestClient(_build_app("certifs-admin"))
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_require_role_correct_role_returns_200(monkeypatch, settings, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setattr(auth, "get_keycloak_public_key", lambda s: public_pem)
    token = _make_token(private_pem, settings, roles=["certifs-admin"])

    client = TestClient(_build_app("certifs-admin"))
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["sub"] == "user-123"
