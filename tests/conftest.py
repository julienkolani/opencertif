import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from core import config as config_module

CORS_TEST_ORIGIN = "https://certifs.example.com"


def _make_blank_pdf(path: Path, pages: int = 1) -> None:
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    for _ in range(pages):
        c.showPage()
    c.save()


@pytest.fixture
def positions_data():
    return {
        "participation": {
            "template_file": "Certificat_participation.pdf",
            "name_position": {"x": 421, "y": 300},
            "name_font": "Helvetica-Bold",
            "name_max_size": 36,
            "name_min_size": 18,
            "name_max_width": 500,
            "qr_position": {"x": 50, "y": 50},
            "qr_size": 80,
            "pages": 1,
            "name_page": 1,
        }
    }


@pytest.fixture
def app_env(tmp_path, monkeypatch, positions_data):
    """Configures Settings (via env vars) for a full FastAPI app under test."""
    templates_dir = tmp_path / "templates"
    certifs_dir = tmp_path / "certifs"
    templates_dir.mkdir()
    certifs_dir.mkdir()

    _make_blank_pdf(templates_dir / "Certificat_participation.pdf", pages=1)

    positions_file = tmp_path / "template_positions.json"
    positions_file.write_text(json.dumps(positions_data), encoding="utf-8")

    monkeypatch.setenv("BASE_URL", "https://certifs.example.com")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "certificates.db"))
    monkeypatch.setenv("TEMPLATES_DIR", str(templates_dir))
    monkeypatch.setenv("CERTIFS_DIR", str(certifs_dir))
    monkeypatch.setenv("POSITIONS_FILE", str(positions_file))
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("CORS_ORIGINS", CORS_TEST_ORIGIN)
    config_module.get_settings.cache_clear()

    yield config_module.get_settings()

    config_module.get_settings.cache_clear()


@pytest.fixture
def client(app_env):
    import main  # imported lazily: api/ is only put on sys.path by the root conftest

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def sample_certificate(client, tmp_path):
    """Inserts one certificate directly in DB (bypassing the API) for read-path tests."""
    from core.db import insert_certificate
    from core.utils import sha256_of_bytes

    pdf_path = tmp_path / "sample_output.pdf"
    pdf_bytes = b"%PDF-1.4 sample certificate content"
    pdf_path.write_bytes(pdf_bytes)

    cert = {
        "id": "cert-fixture-id",
        "name": "Kolani",
        "first_name": "Julien",
        "event_name": "IndabaX Togo 2026",
        "event_date": "2026-03-15",
        "cert_type": "participation",
        "generated_at": "2026-03-15T10:00:00+00:00",
        "generated_by": "admin@example.com",
        "pdf_path": str(pdf_path),
        "pdf_checksum": sha256_of_bytes(pdf_bytes),
        "email_sent_at": None,
    }
    insert_certificate(cert)

    return {"cert": cert, "pdf_bytes": pdf_bytes}
