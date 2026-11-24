import smtplib
from email import message_from_string
from email.header import decode_header
from pathlib import Path

import pytest

from core import config as config_module
from core import db
from core import mailer


@pytest.fixture
def settings(tmp_path, monkeypatch):
    db_path = tmp_path / "certificates.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    config_module.get_settings.cache_clear()
    db.init_db()
    yield config_module.get_settings()
    config_module.get_settings.cache_clear()


@pytest.fixture
def sample_pdf(tmp_path):
    pdf_path = tmp_path / "certificate.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")
    return str(pdf_path)


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def noop(self):
        return (250, b"OK")

    def login(self, user, password):
        self.logged_in = (user, password)

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent = (from_addr, to_addrs, msg)


class _FakeSMTP_SSL(_FakeSMTP):
    """Distinct class so tests can assert SMTP_SSL was used for security='ssl'."""


class _FailingSMTP(_FakeSMTP):
    def sendmail(self, from_addr, to_addrs, msg):
        raise smtplib.SMTPException("boom")


def test_send_certificate_email_success(monkeypatch, settings, sample_pdf):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)

    result = mailer.send_certificate_email(
        to_email="julien@example.com",
        name="Kolani",
        first_name="Julien",
        event_name="IndabaX Togo 2026",
        event_date="2026-03-15",
        pdf_path=sample_pdf,
        verify_url="https://certifs.example.com/verifier?code=abc123",
    )

    assert result is True
    assert len(_FakeSMTP.instances) == 1
    sent_instance = _FakeSMTP.instances[0]
    assert sent_instance.started_tls is True
    assert sent_instance.logged_in == ("user@example.com", "secret")
    assert sent_instance.sent[0] == "noreply@example.com"
    assert sent_instance.sent[1] == ["julien@example.com"]

    parsed = message_from_string(sent_instance.sent[2])

    subject_parts = decode_header(parsed["Subject"])
    subject = "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in subject_parts
    )
    assert "IndabaX Togo 2026" in subject

    html_part = next(p for p in parsed.walk() if p.get_content_type() == "text/html")
    html_body = html_part.get_payload(decode=True).decode("utf-8")
    assert "IndabaX Togo 2026" in html_body
    assert "Julien" in html_body and "Kolani" in html_body
    assert "verifier?code=abc123" in html_body

    pdf_part = next(p for p in parsed.walk() if p.get_content_type() == "application/pdf")
    assert pdf_part.get_payload(decode=True) == Path(sample_pdf).read_bytes()
    assert pdf_part.get_filename() == "certificate.pdf"


def test_send_certificate_email_smtp_failure_returns_false(monkeypatch, settings, sample_pdf):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FailingSMTP)

    result = mailer.send_certificate_email(
        to_email="julien@example.com",
        name="Kolani",
        first_name="Julien",
        event_name="IndabaX Togo 2026",
        event_date="2026-03-15",
        pdf_path=sample_pdf,
    )

    assert result is False


def test_send_certificate_email_missing_pdf_returns_false(monkeypatch, settings, tmp_path):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    missing_path = str(tmp_path / "does-not-exist.pdf")

    result = mailer.send_certificate_email(
        to_email="julien@example.com",
        name="Kolani",
        first_name="Julien",
        event_name="IndabaX Togo 2026",
        event_date="2026-03-15",
        pdf_path=missing_path,
    )

    assert result is False


def test_send_certificate_email_no_host_returns_false(monkeypatch, settings, sample_pdf):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)

    result = mailer.send_certificate_email(
        to_email="julien@example.com",
        name="Kolani",
        first_name="Julien",
        event_name="IndabaX Togo 2026",
        event_date="2026-03-15",
        pdf_path=sample_pdf,
    )

    assert result is False


def test_db_setting_overrides_env(monkeypatch, settings, sample_pdf):
    """settings table takes priority over env vars, per _get_smtp_params' own doc."""
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    db.set_setting("smtp_host", "db-smtp.example.com")
    db.set_setting("smtp_from", "db-noreply@example.com")

    result = mailer.send_certificate_email(
        to_email="julien@example.com",
        name="Kolani",
        first_name="Julien",
        event_name="IndabaX Togo 2026",
        event_date="2026-03-15",
        pdf_path=sample_pdf,
    )

    assert result is True
    sent_instance = _FakeSMTP.instances[0]
    assert sent_instance.host == "db-smtp.example.com"
    assert sent_instance.sent[0] == "db-noreply@example.com"


def test_send_certificate_email_ssl_security_uses_smtp_ssl(monkeypatch, settings, sample_pdf):
    _FakeSMTP_SSL.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _FakeSMTP_SSL)
    db.set_setting("smtp_security", "ssl")

    result = mailer.send_certificate_email(
        to_email="julien@example.com",
        name="Kolani",
        first_name="Julien",
        event_name="IndabaX Togo 2026",
        event_date="2026-03-15",
        pdf_path=sample_pdf,
    )

    assert result is True
    assert len(_FakeSMTP_SSL.instances) == 1
    assert _FakeSMTP_SSL.instances[0].started_tls is False


def test_test_smtp_connection_no_host_configured(monkeypatch, settings):
    monkeypatch.setenv("SMTP_HOST", "")

    ok, message = mailer.test_smtp_connection()

    assert ok is False
    assert "non configuré" in message.lower()


def test_test_smtp_connection_success(monkeypatch, settings):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)

    ok, message = mailer.test_smtp_connection()

    assert ok is True
    assert "smtp.example.com" in message
