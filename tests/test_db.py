import pytest

from core import config as config_module
from core import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "certificates.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    config_module.get_settings.cache_clear()
    db.init_db()
    yield db_path
    config_module.get_settings.cache_clear()


def make_cert(**overrides):
    cert = {
        "id": "abc123",
        "name": "Kolani",
        "first_name": "Julien",
        "event_name": "IndabaX Togo 2026",
        "event_date": "2026-03-15",
        "cert_type": "participation",
        "generated_at": "2026-03-15T10:00:00",
        "generated_by": "admin@example.com",
        "pdf_path": "data/certifs/2026/participation/abc123_KOLANI_Julien.pdf",
        "pdf_checksum": "deadbeef",
        "email_sent_at": None,
    }
    cert.update(overrides)
    return cert


def test_insert_and_get_by_id(temp_db):
    cert = make_cert()
    db.insert_certificate(cert)

    fetched = db.get_certificate_by_id(cert["id"])

    assert fetched is not None
    assert fetched["name"] == "Kolani"
    assert fetched["first_name"] == "Julien"
    assert fetched["pdf_checksum"] == "deadbeef"


def test_get_by_id_not_found(temp_db):
    assert db.get_certificate_by_id("does-not-exist") is None


def test_get_by_checksum(temp_db):
    cert = make_cert(id="cert-2", pdf_checksum="checksum-xyz")
    db.insert_certificate(cert)

    fetched = db.get_certificate_by_checksum("checksum-xyz")

    assert fetched is not None
    assert fetched["id"] == "cert-2"
    assert db.get_certificate_by_checksum("unknown") is None


def test_duplicate_raises(temp_db):
    cert = make_cert()
    db.insert_certificate(cert)

    duplicate = make_cert(id="different-id")

    with pytest.raises(db.DuplicateCertificateError):
        db.insert_certificate(duplicate)


def test_check_duplicate(temp_db):
    cert = make_cert()
    db.insert_certificate(cert)

    assert db.check_duplicate("Kolani", "Julien", "IndabaX Togo 2026", "2026-03-15") is True
    assert db.check_duplicate("Kolani", "Julien", "IndabaX Togo 2026", "2027-03-15") is False


def test_list_certificates_filters_and_pagination(temp_db):
    db.insert_certificate(make_cert(
        id="c1", name="Kolani", first_name="Julien",
        event_name="IndabaX Togo 2026", event_date="2026-03-15", cert_type="participation",
    ))
    db.insert_certificate(make_cert(
        id="c2", name="Mensah", first_name="Ama",
        event_name="IndabaX Togo 2026", event_date="2026-03-15", cert_type="organisation",
    ))
    db.insert_certificate(make_cert(
        id="c3", name="Adjo", first_name="Koffi",
        event_name="PyCon Togo 2025", event_date="2025-06-01", cert_type="participation",
    ))

    results, total = db.list_certificates(filters={}, page=1, per_page=20)
    assert total == 3
    assert len(results) == 3

    results, total = db.list_certificates(filters={"cert_type": "organisation"}, page=1, per_page=20)
    assert total == 1
    assert results[0]["id"] == "c2"

    results, total = db.list_certificates(filters={"year": "2026"}, page=1, per_page=20)
    assert total == 2
    assert {r["id"] for r in results} == {"c1", "c2"}

    results, total = db.list_certificates(filters={"search": "Mensah"}, page=1, per_page=20)
    assert total == 1
    assert results[0]["id"] == "c2"

    results, total = db.list_certificates(filters={}, page=1, per_page=2)
    assert total == 3
    assert len(results) == 2

    results, total = db.list_certificates(filters={}, page=2, per_page=2)
    assert total == 3
    assert len(results) == 1


def test_init_db_enables_wal_journal_mode(temp_db):
    """WAL keeps reads (public verification) working during writes; it is
    stored in the database file, so it must be set by init_db()."""
    import sqlite3

    from core.config import get_settings

    db.init_db()
    conn = sqlite3.connect(get_settings().DB_PATH)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
