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


CSS_TEMPLATE = (
    "<html><head><style>p { margin: 0; } .btn { color: #fff; }</style></head>"
    "<body><p>Salut {prenom} {nom}</p><a href=\"{url_verification}\">{evenement}</a></body></html>"
)


def test_custom_template_with_css_braces_is_used_not_default(monkeypatch, settings, sample_pdf):
    """Regression: str.format() raised on CSS braces and silently fell back
    to DEFAULT_EMAIL_TEMPLATE, whatever template the admin had saved."""
    db.set_setting("smtp_email_template", CSS_TEMPLATE)
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)

    assert mailer.send_certificate_email(
        to_email="julien@example.com", name="Kolani", first_name="Julien",
        event_name="IndabaX Togo 2026", event_date="2026-03-15",
        pdf_path=sample_pdf, verify_url="https://certifs.example.com/verifier?code=abc123",
    ) is True

    parsed = message_from_string(_FakeSMTP.instances[0].sent[2])
    html_part = next(p for p in parsed.walk() if p.get_content_type() == "text/html")
    html_body = html_part.get_payload(decode=True).decode("utf-8")
    assert "Salut Julien Kolani" in html_body
    assert "p { margin: 0; }" in html_body
    assert "Félicitations" not in html_body  # default template text


def test_render_template_escapes_values_but_not_subject():
    values = {"prenom": "<b>Jo</b>", "nom": "O'Neil & Co", "evenement": "A & B"}
    assert mailer.render_template("{prenom} {nom}", values) == "&lt;b&gt;Jo&lt;/b&gt; O&#x27;Neil &amp; Co"
    assert mailer.render_template("Votre certificat : {evenement}", values, escape_html=False) == "Votre certificat : A & B"
    assert mailer.render_template("{inconnu} {{x}}", values) == "{inconnu} {{x}}"


def _send(sample_pdf, **kwargs):
    return mailer.send_certificate_email(
        to_email="julien@example.com", name="Kolani", first_name="Julien",
        event_name="IndabaX Togo 2026", event_date="2026-03-15",
        pdf_path=sample_pdf, verify_url="https://certifs.example.com/verifier?code=abc",
        **kwargs,
    )


def test_successful_send_is_logged_with_html(monkeypatch, settings, sample_pdf):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)

    assert _send(sample_pdf, cert_id="c1", kind="batch", sent_by="oc-admin") is True

    items, total = db.list_email_log()
    assert total == 1
    entry = db.get_email_log(items[0]["id"])
    assert entry["recipient"] == "julien@example.com"
    assert entry["status"] == "envoye" and entry["error"] is None
    assert entry["kind"] == "batch" and entry["sent_by"] == "oc-admin"
    assert entry["cert_id"] == "c1" and entry["event_name"] == "IndabaX Togo 2026"
    assert "IndabaX Togo 2026" in entry["subject"]
    assert "Julien" in entry["html_body"]
    assert "html_body" not in items[0]  # list view stays light


def test_smtp_failure_is_logged_with_error(monkeypatch, settings, sample_pdf):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FailingSMTP)

    assert _send(sample_pdf) is False

    entry = db.list_email_log()[0][0]
    assert entry["status"] == "echec"
    assert "boom" in entry["error"]


def test_missing_pdf_and_missing_smtp_are_logged(monkeypatch, settings, tmp_path, sample_pdf):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    assert _send(str(tmp_path / "absent.pdf")) is False
    monkeypatch.delenv("SMTP_HOST")
    assert _send(sample_pdf) is False

    errors = [e["error"] for e in db.list_email_log(status="echec")[0]]
    assert any("SMTP non configuré" in e for e in errors)
    assert any("PDF illisible" in e for e in errors)


def test_log_write_failure_does_not_break_sending(monkeypatch, settings, sample_pdf):
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)

    def broken(_entry):
        raise RuntimeError("disk full")

    monkeypatch.setattr(mailer, "insert_email_log", broken)
    assert _send(sample_pdf) is True


def test_list_email_log_filters_and_paginates(settings):
    for i in range(5):
        mailer.record_email(f"user{i}@example.com", "S", "masse" if i % 2 else "test",
                            "echec" if i == 4 else "envoye", event_name="Evt A" if i < 3 else "Evt B")

    assert db.list_email_log()[1] == 5
    assert db.list_email_log()[0][0]["recipient"] == "user4@example.com"  # newest first
    assert db.list_email_log(status="echec")[1] == 1
    assert db.list_email_log(kind="masse")[1] == 2
    assert db.list_email_log(event_name="evt b")[1] == 2  # LIKE is case-insensitive
    assert db.list_email_log(recipient="user1")[1] == 1
    page2, total = db.list_email_log(limit=2, offset=2)
    assert total == 5 and [e["recipient"] for e in page2] == ["user2@example.com", "user1@example.com"]
