"""Confirms each protected router actually wires require_role/require_any_role,
independent of the DEV_MODE=true bypass used by the `client` fixture elsewhere.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import config as config_module


@pytest.fixture
def no_dev_mode_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "certificates.db"))
    monkeypatch.setenv("POSITIONS_FILE", str(tmp_path / "template_positions.json"))
    monkeypatch.setenv("KEYCLOAK_URL", "https://auth.example.com")
    monkeypatch.setenv("KEYCLOAK_REALM", "opencertif")
    config_module.get_settings.cache_clear()

    yield

    config_module.get_settings.cache_clear()


def test_certificates_generate_requires_auth(no_dev_mode_settings):
    from routers import certificates

    app = FastAPI()
    app.include_router(certificates.router, prefix="/api/certificates")
    client = TestClient(app)

    response = client.post(
        "/api/certificates/generate",
        json={
            "name": "Kolani",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "participation",
        },
    )

    assert response.status_code == 401


def test_history_requires_auth(no_dev_mode_settings):
    from routers import history

    app = FastAPI()
    app.include_router(history.router, prefix="/api/history")
    client = TestClient(app)

    response = client.get("/api/history")

    assert response.status_code == 401


def test_templates_list_requires_auth(no_dev_mode_settings):
    from routers import templates

    app = FastAPI()
    app.include_router(templates.router, prefix="/api/templates")
    client = TestClient(app)

    response = client.get("/api/templates")

    assert response.status_code == 401


def test_batch_rows_requires_auth(no_dev_mode_settings):
    from routers import certificates

    app = FastAPI()
    app.include_router(certificates.router, prefix="/api/certificates")
    client = TestClient(app)

    response = client.post("/api/certificates/batch-rows", json={"rows": []})

    assert response.status_code == 401
