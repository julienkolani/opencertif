import io
import json
import zipfile

import openpyxl
from pypdf import PdfReader


def _build_excel(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- POST /generate ---


def test_generate_certificate_success(client):
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

    assert response.status_code == 200
    body = response.json()
    assert "id" in body and len(body["id"]) == 32
    assert body["pdf_url"] == f"/api/certificates/{body['id']}/pdf"
    assert body["qr_content"] == f"https://certifs.example.com/verifier?code={body['id']}"


def test_generate_certificate_missing_field_returns_400(client):
    response = client.post(
        "/api/certificates/generate",
        json={
            "name": "  ",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "participation",
        },
    )

    assert response.status_code == 400


def test_generate_certificate_unknown_type_returns_400(client):
    response = client.post(
        "/api/certificates/generate",
        json={
            "name": "Kolani",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "does-not-exist",
        },
    )

    assert response.status_code == 400


def test_generate_certificate_invalid_date_returns_400(client):
    response = client.post(
        "/api/certificates/generate",
        json={
            "name": "Kolani",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "not-a-date",
            "cert_type": "participation",
        },
    )

    assert response.status_code == 400


def test_generate_certificate_sends_email_when_requested(client, monkeypatch):
    import routers.certificates as certificates_module

    sent_emails: list[str] = []

    def fake_send_email(**kwargs):
        sent_emails.append(kwargs["to_email"])
        return True

    monkeypatch.setattr(certificates_module, "send_certificate_email", fake_send_email)

    response = client.post(
        "/api/certificates/generate",
        json={
            "name": "Kolani",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "participation",
            "email": "julien@example.com",
            "send_email": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email_sent"] is True
    assert sent_emails == ["julien@example.com"]


def test_generate_certificate_does_not_send_email_by_default(client, monkeypatch):
    import routers.certificates as certificates_module

    def fail_if_called(**kwargs):
        raise AssertionError("send_certificate_email should not be called")

    monkeypatch.setattr(certificates_module, "send_certificate_email", fail_if_called)

    response = client.post(
        "/api/certificates/generate",
        json={
            "name": "Kolani",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "participation",
            "email": "julien@example.com",
        },
    )

    assert response.status_code == 200
    assert response.json()["email_sent"] is False


def test_generate_certificate_duplicate_returns_409(client):
    payload = {
        "name": "Kolani",
        "first_name": "Julien",
        "event_name": "IndabaX Togo 2026",
        "event_date": "2026-03-15",
        "cert_type": "participation",
    }

    first = client.post("/api/certificates/generate", json=payload)
    assert first.status_code == 200

    second = client.post("/api/certificates/generate", json=payload)
    assert second.status_code == 409


# --- GET /{id}/pdf ---


def test_download_certificate_pdf(client):
    generate_response = client.post(
        "/api/certificates/generate",
        json={
            "name": "Mensah",
            "first_name": "Ama",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "participation",
        },
    )
    cert_id = generate_response.json()["id"]

    response = client.get(f"/api/certificates/{cert_id}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) == 1


def test_download_certificate_pdf_not_found_returns_404(client):
    response = client.get("/api/certificates/does-not-exist/pdf")

    assert response.status_code == 404


# --- POST /batch ---


def test_batch_generate_success(client, monkeypatch):
    import routers.certificates as certificates_module

    sent_emails: list[str] = []

    def fake_send_email(**kwargs):
        sent_emails.append(kwargs["to_email"])
        return True

    monkeypatch.setattr(certificates_module, "send_certificate_email", fake_send_email)

    excel_bytes = _build_excel(
        headers=["Nom complet", "Prenom", "Evenement", "DateEvt", "Mail"],
        rows=[
            ["Kolani", "Julien", "IndabaX Togo 2026", "2026-03-15", "julien@example.com"],
            ["Mensah", "Ama", "IndabaX Togo 2026", "2026-03-15", ""],
            ["", "Koffi", "IndabaX Togo 2026", "2026-03-15", ""],
        ],
    )

    mapping = {
        "name": "Nom complet",
        "first_name": "Prenom",
        "event_name": "Evenement",
        "event_date": "DateEvt",
        "email": "Mail",
    }

    response = client.post(
        "/api/certificates/batch",
        files={
            "file": (
                "import.xlsx",
                excel_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={
            "column_mapping": json.dumps(mapping),
            "default_cert_type": "participation",
            "send_email": "true",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] == 2
    assert body["duplicates"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 4
    assert body["emails_sent"] == 1
    assert sent_emails == ["julien@example.com"]
    assert body["zip_url"] is not None

    zip_response = client.get(body["zip_url"])
    assert zip_response.status_code == 200
    assert zip_response.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(zip_response.content))
    assert len(archive.namelist()) == 2


def test_batch_duplicate_row_is_counted_not_errored(client):
    client.post(
        "/api/certificates/generate",
        json={
            "name": "Kolani",
            "first_name": "Julien",
            "event_name": "IndabaX Togo 2026",
            "event_date": "2026-03-15",
            "cert_type": "participation",
        },
    )

    excel_bytes = _build_excel(
        headers=["Nom", "Prenom", "Evenement", "Date"],
        rows=[["Kolani", "Julien", "IndabaX Togo 2026", "2026-03-15"]],
    )
    mapping = {
        "name": "Nom",
        "first_name": "Prenom",
        "event_name": "Evenement",
        "event_date": "Date",
    }

    response = client.post(
        "/api/certificates/batch",
        files={
            "file": (
                "import.xlsx",
                excel_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"column_mapping": json.dumps(mapping), "default_cert_type": "participation"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] == 0
    assert body["duplicates"] == 1
    assert body["errors"] == []
    assert body["zip_url"] is None


def test_batch_invalid_mapping_json_returns_400(client):
    response = client.post(
        "/api/certificates/batch",
        files={"file": ("import.xlsx", b"not a real xlsx", "application/octet-stream")},
        data={"column_mapping": "{not valid json"},
    )

    assert response.status_code == 400


def test_batch_missing_required_mapping_fields_returns_400(client):
    excel_bytes = _build_excel(headers=["A"], rows=[["x"]])

    response = client.post(
        "/api/certificates/batch",
        files={
            "file": (
                "import.xlsx",
                excel_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"column_mapping": json.dumps({"name": "A"})},
    )

    assert response.status_code == 400


def test_batch_with_default_event_name_and_date(client):
    """event_name/event_date can be set once for the whole batch instead of mapped."""
    excel_bytes = _build_excel(
        headers=["Nom", "Prenom"],
        rows=[
            ["Kolani", "Julien"],
            ["Mensah", "Ama"],
        ],
    )
    mapping = {"name": "Nom", "first_name": "Prenom"}

    response = client.post(
        "/api/certificates/batch",
        files={
            "file": (
                "import.xlsx",
                excel_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={
            "column_mapping": json.dumps(mapping),
            "default_cert_type": "participation",
            "default_event_name": "IndabaX Togo 2026",
            "default_event_date": "2026-03-15",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] == 2
    assert body["errors"] == []

    history = client.get("/api/history")
    items = {item["name"]: item for item in history.json()["items"]}
    assert items["Kolani"]["event_name"] == "IndabaX Togo 2026"
    assert items["Kolani"]["event_date"] == "2026-03-15"
    assert items["Mensah"]["event_name"] == "IndabaX Togo 2026"


def test_batch_missing_event_fields_without_defaults_returns_400(client):
    excel_bytes = _build_excel(headers=["Nom", "Prenom"], rows=[["Kolani", "Julien"]])

    response = client.post(
        "/api/certificates/batch",
        files={
            "file": (
                "import.xlsx",
                excel_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={
            "column_mapping": json.dumps({"name": "Nom", "first_name": "Prenom"}),
            "default_cert_type": "participation",
        },
    )

    assert response.status_code == 400
    assert "event_name" in response.json()["detail"]
    assert "event_date" in response.json()["detail"]


# --- POST /batch-rows (pre-cleaned grid, no Excel file) ---


def test_batch_rows_generate_success(client, monkeypatch):
    import routers.certificates as certificates_module

    sent_emails: list[str] = []

    def fake_send_email(**kwargs):
        sent_emails.append(kwargs["to_email"])
        return True

    monkeypatch.setattr(certificates_module, "send_certificate_email", fake_send_email)

    response = client.post(
        "/api/certificates/batch-rows",
        json={
            "rows": [
                {
                    "name": "Kolani",
                    "first_name": "Julien",
                    "event_name": "IndabaX Togo 2026",
                    "event_date": "2026-03-15",
                    "cert_type": "participation",
                    "email": "julien@example.com",
                },
                {
                    "name": "Mensah",
                    "first_name": "Ama",
                    "event_name": "IndabaX Togo 2026",
                    "event_date": "2026-03-15",
                    "cert_type": "participation",
                    "email": "",
                },
            ],
            "send_email": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] == 2
    assert body["duplicates"] == 0
    assert body["errors"] == []
    assert body["emails_sent"] == 1
    assert sent_emails == ["julien@example.com"]
    assert body["zip_url"] is not None


def test_batch_rows_reports_position_not_excel_row(client):
    """/batch-rows has no source spreadsheet, so row numbers are 1-based
    positions in the submitted list (unlike /batch's Excel row numbers)."""
    response = client.post(
        "/api/certificates/batch-rows",
        json={
            "rows": [
                {"name": "Kolani", "first_name": "Julien", "event_name": "", "event_date": "2026-03-15", "cert_type": "participation"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["errors"] == [{"row": 1, "error": "Champs obligatoires manquants."}]


def test_batch_rows_unknown_cert_type_is_reported(client):
    response = client.post(
        "/api/certificates/batch-rows",
        json={
            "rows": [
                {
                    "name": "Kolani",
                    "first_name": "Julien",
                    "event_name": "IndabaX Togo 2026",
                    "event_date": "2026-03-15",
                    "cert_type": "does-not-exist",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] == 0
    assert "inconnu" in body["errors"][0]["error"]


def test_batch_endpoint_is_sync_not_async():
    """generate_batch_endpoint must stay a plain `def`: it does synchronous,
    blocking work (PDF rendering, disk I/O, SQLite) end to end, and as a
    plain function FastAPI dispatches it to a worker thread instead of
    running it on the shared asyncio event loop; otherwise one admin's
    big batch freezes /verifier and every other request for everyone else.
    """
    import inspect

    import routers.certificates as certificates_module

    assert not inspect.iscoroutinefunction(certificates_module.generate_batch_endpoint)


def test_batch_zip_unknown_batch_id_returns_404(client):
    response = client.get("/api/certificates/batch/0123456789abcdef/zip")

    assert response.status_code == 404


def test_batch_zip_invalid_batch_id_format_returns_400(client):
    response = client.get("/api/certificates/batch/does-not-exist/zip")

    assert response.status_code == 400


def _assert_saved_before_send(monkeypatch):
    """Patches the mailer so each email checks its certificate is already in
    the database: the email's verification link must resolve on arrival."""
    import routers.certificates as certificates_module
    from core.db import get_certificate_by_id

    seen: list[str] = []

    def fake_send_email(**kwargs):
        assert get_certificate_by_id(kwargs["cert_id"]) is not None, "email sent before the certificate was saved"
        seen.append(kwargs["cert_id"])
        return True

    monkeypatch.setattr(certificates_module, "send_certificate_email", fake_send_email)
    return seen


def test_generate_saves_certificate_before_emailing(client, monkeypatch):
    from core.db import get_certificate_by_id

    seen = _assert_saved_before_send(monkeypatch)
    body = client.post("/api/certificates/generate", json={
        "name": "Kolani", "first_name": "Julien", "event_name": "Ordre", "event_date": "2026-03-15",
        "cert_type": "participation", "email": "julien@example.com", "send_email": True,
    }).json()

    assert seen == [body["id"]] and body["email_sent"] is True
    assert get_certificate_by_id(body["id"])["email_sent_at"] is not None


def test_batch_rows_save_certificates_before_emailing(client, monkeypatch):
    from core.db import get_certificate_by_id

    seen = _assert_saved_before_send(monkeypatch)
    body = client.post("/api/certificates/batch-rows", json={"send_email": True, "rows": [
        {"name": "A", "first_name": "Un", "event_name": "Ordre B", "event_date": "2026-03-15",
         "cert_type": "participation", "email": "a@example.com"},
        {"name": "B", "first_name": "Deux", "event_name": "Ordre B", "event_date": "2026-03-15",
         "cert_type": "participation", "email": ""},
    ]}).json()

    assert body["generated"] == 2 and body["emails_sent"] == 1 and len(seen) == 1
    assert get_certificate_by_id(seen[0])["email_sent_at"] is not None
