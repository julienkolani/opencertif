import smtplib

import pytest


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        pass

    def noop(self):
        return (250, b"OK")

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent = (from_addr, to_addrs, msg)


@pytest.fixture
def insert_cert_with_email(app_env):
    from core.db import insert_certificate
    from core.utils import sha256_of_bytes

    def _insert(cert_id, email="julien@example.com", email_sent_at=None, pdf_path=None, **overrides):
        pdf_path = pdf_path or str(app_env.CERTIFS_DIR)
        cert = {
            "id": cert_id,
            "name": "Kolani",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "participation",
            "generated_at": "2026-03-15T10:00:00+00:00",
            "generated_by": "admin@example.com",
            "pdf_path": pdf_path,
            "pdf_checksum": sha256_of_bytes(cert_id.encode()),
            "email": email,
            "email_sent_at": email_sent_at,
        }
        cert.update(overrides)
        insert_certificate(cert)
        return cert

    return _insert


def test_get_config_not_configured(client):
    response = client.get("/api/email/config")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert "password" not in body


def test_update_config_persists_and_get_reflects_it(client):
    payload = {
        "host": "smtp.example.com",
        "port": 587,
        "user": "user@example.com",
        "password": "supersecret",
        "from_addr": "noreply@example.com",
        "security": "starttls",
        "email_subject": "Votre certificat : {evenement}",
        "email_template": "",
    }

    update_response = client.post("/api/email/config", json=payload)
    assert update_response.status_code == 200

    get_response = client.get("/api/email/config")
    body = get_response.json()
    assert body["host"] == "smtp.example.com"
    assert body["configured"] is True
    assert "password" not in body


def test_test_config_reports_failure_without_host(client):
    response = client.post("/api/email/test", json={"to_email": "someone@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False


def test_preview_returns_subject_and_html(client):
    response = client.get("/api/email/preview")

    assert response.status_code == 200
    body = response.json()
    assert "Jean" in body["html"]
    assert "subject" in body


def _configure_smtp(client, monkeypatch, template="", subject="Votre certificat : {evenement}"):
    client.post(
        "/api/email/config",
        json={
            "host": "smtp.example.com", "port": 587, "user": "", "password": "",
            "from_addr": "noreply@example.com", "security": "starttls",
            "email_subject": subject, "email_template": template,
        },
    )
    import core.mailer as mailer_module

    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer_module.smtplib, "SMTP", _FakeSMTP)


def _sent_html_and_subject():
    from email import message_from_string
    from email.header import decode_header, make_header

    sent = next(i.sent for i in _FakeSMTP.instances if i.sent)
    parsed = message_from_string(sent[2])
    html_part = next(p for p in parsed.walk() if p.get_content_type() == "text/html")
    return html_part.get_payload(decode=True).decode("utf-8"), str(make_header(decode_header(parsed["Subject"])))


def test_test_email_uses_saved_template(client, monkeypatch):
    """Regression: the test email used to be a hardcoded plain-text message."""
    _configure_smtp(client, monkeypatch, template="<style>p { color: red; }</style><p>Coucou {prenom}</p>")

    body = client.post("/api/email/test", json={"to_email": "doc@example.com"}).json()

    assert body["ok"] is True, body
    html, subject = _sent_html_and_subject()
    assert "Coucou Jean" in html and "p { color: red; }" in html
    assert subject == "[Test] Votre certificat : Formation Python"


def test_test_email_uses_unsaved_draft_over_saved_template(client, monkeypatch):
    _configure_smtp(client, monkeypatch, template="<p>Ancien {prenom}</p>")

    client.post("/api/email/test", json={
        "to_email": "doc@example.com",
        "email_template": "<p>Brouillon {nom}</p>",
        "email_subject": "Attestation {evenement}",
    })

    html, subject = _sent_html_and_subject()
    assert "Brouillon Dupont" in html and "Ancien" not in html
    assert subject == "[Test] Attestation Formation Python"


def test_preview_post_renders_draft_with_css_braces(client):
    response = client.post("/api/email/preview", json={
        "email_template": "<style>.x { margin: 0 }</style><p>{prenom} {evenement}</p>",
    })

    assert response.status_code == 200
    assert "<p>Jean Formation Python</p>" in response.json()["html"]
    assert ".x { margin: 0 }" in response.json()["html"]


def test_send_emails_returns_job_id_and_completes(client, monkeypatch, insert_cert_with_email, tmp_path):
    pdf_path = tmp_path / "cert.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    insert_cert_with_email("cert-1", email="julien@example.com", pdf_path=str(pdf_path))

    client.post(
        "/api/email/config",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "user": "",
            "password": "",
            "from_addr": "noreply@example.com",
            "security": "starttls",
            "email_subject": "Votre certificat : {evenement}",
            "email_template": "",
        },
    )

    import core.mailer as mailer_module

    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer_module.smtplib, "SMTP", _FakeSMTP)

    response = client.post("/api/email/send", json={"only_unsent": True})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert response.json()["total"] == 1

    poll = client.get(f"/api/email/send/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "done"
    result = poll.json()["result"]
    assert result["sent"] == 1
    assert result["total"] == 1


def test_send_emails_skips_already_sent_by_default(client, insert_cert_with_email):
    insert_cert_with_email("cert-already-sent", email_sent_at="2026-01-01T00:00:00+00:00")

    response = client.post("/api/email/send", json={"only_unsent": True})

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_get_send_job_unknown_returns_404(client):
    response = client.get("/api/email/send/does-not-exist")

    assert response.status_code == 404
