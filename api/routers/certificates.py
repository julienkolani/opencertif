import io
import json
import re
import secrets
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.auth import require_role
from core.certgen import generate_certificate, get_available_types
from core.config import Settings, get_settings
from core.db import DuplicateCertificateError, check_duplicate, get_certificate_by_id, insert_certificate
from core.mailer import send_certificate_email
from core.utils import normalize_event_date, sha256_of_file

router = APIRouter()

# name/first_name identify a person and must come from a column, one per row.
# event_name/event_date are very often the same for an entire batch (one
# Excel export per event), so they can instead be set once for all rows,
# see default_event_name/default_event_date below.
REQUIRED_ROW_FIELDS = ["name", "first_name"]
_DEFAULTABLE_ROW_FIELDS = ["event_name", "event_date"]
_OPTIONAL_FIELDS = {"email"}


class CertificateGenerateRequest(BaseModel):
    name: str
    first_name: str
    event_name: str
    event_date: str
    cert_type: str
    email: str = ""
    send_email: bool = False


class CertificateGenerateResponse(BaseModel):
    id: str
    pdf_url: str
    qr_content: str
    email_sent: bool = False


class BatchRowInput(BaseModel):
    name: str = ""
    first_name: str = ""
    event_name: str = ""
    event_date: str = ""
    cert_type: str = ""
    email: str = ""


class BatchRowsRequest(BaseModel):
    rows: list[BatchRowInput]
    send_email: bool = False


def _current_username(user: dict[str, Any]) -> str | None:
    return user.get("preferred_username") or user.get("email") or user.get("sub")


def _generate_from_rows(
    rows: list[dict[str, Any]],
    send_email: bool,
    settings: Settings,
    user: dict[str, Any],
    start_index: int = 1,
) -> dict[str, Any]:
    """Core batch loop: validate/generate/insert/email one certificate per row.

    Shared by /batch (raw Excel + column mapping) and /batch-rows (rows the
    admin has already resolved and cleaned client-side, e.g. via the batch
    editor grid) so the two entry points can't drift out of sync.

    start_index sets what the first row is called in error messages: /batch
    passes 2 so "row" matches the actual Excel row number (row 1 is the
    header); /batch-rows passes the default 1 (position in the submitted,
    already-edited list; there's no original spreadsheet row to refer to).
    """
    available_types = get_available_types(settings.POSITIONS_FILE)

    generated = 0
    duplicates = 0
    emails_sent = 0
    errors: list[dict[str, Any]] = []
    generated_pdf_paths: list[str] = []

    for row_index, row in enumerate(rows, start=start_index):
        name = (row.get("name") or "").strip() or None
        first_name = (row.get("first_name") or "").strip() or None
        event_name = (row.get("event_name") or "").strip() or None
        raw_event_date = (row.get("event_date") or "").strip() or None
        cert_type = (row.get("cert_type") or "").strip() or None
        email = (row.get("email") or "").strip() or None

        if not all([name, first_name, event_name, raw_event_date]):
            errors.append({"row": row_index, "error": "Champs obligatoires manquants."})
            continue

        event_date = normalize_event_date(raw_event_date)
        if event_date is None:
            errors.append({"row": row_index, "error": f"Date invalide : '{raw_event_date}'."})
            continue

        if not cert_type:
            errors.append({"row": row_index, "error": "Type de certificat manquant."})
            continue

        if cert_type not in available_types:
            errors.append({"row": row_index, "error": f"Type de certificat inconnu : '{cert_type}'."})
            continue

        if check_duplicate(name, first_name, event_name, event_date):
            duplicates += 1
            continue

        cert_id = secrets.token_hex(16)
        try:
            pdf_path = generate_certificate(
                name=name,
                first_name=first_name,
                event_name=event_name,
                event_date=event_date,
                cert_type=cert_type,
                cert_id=cert_id,
                settings=settings,
            )
        except (ValueError, FileNotFoundError) as exc:
            errors.append({"row": row_index, "error": f"Erreur de génération : {exc}"})
            continue

        email_sent_at = None
        if send_email and email:
            verify_url = f"{settings.BASE_URL}/verifier?code={cert_id}" if settings.BASE_URL else ""
            if send_certificate_email(
                to_email=email,
                name=name,
                first_name=first_name,
                event_name=event_name,
                event_date=event_date,
                pdf_path=pdf_path,
                verify_url=verify_url,
                cert_id=cert_id,
                kind="batch",
                sent_by=_current_username(user),
            ):
                email_sent_at = datetime.now(timezone.utc).isoformat()
                emails_sent += 1

        cert = {
            "id": cert_id,
            "name": name,
            "first_name": first_name,
            "event_name": event_name,
            "event_date": event_date,
            "cert_type": cert_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": _current_username(user),
            "pdf_path": pdf_path,
            "pdf_checksum": sha256_of_file(pdf_path),
            "email": email,
            "email_sent_at": email_sent_at,
        }

        try:
            insert_certificate(cert)
        except DuplicateCertificateError:
            Path(pdf_path).unlink(missing_ok=True)
            duplicates += 1
            continue

        generated += 1
        generated_pdf_paths.append(pdf_path)

    zip_url = None
    if generated_pdf_paths:
        batch_id = secrets.token_hex(8)
        batches_dir = Path(settings.CERTIFS_DIR) / "_batches"
        batches_dir.mkdir(parents=True, exist_ok=True)
        zip_path = batches_dir / f"{batch_id}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for pdf_path in generated_pdf_paths:
                archive.write(pdf_path, arcname=Path(pdf_path).name)

        zip_url = f"/api/certificates/batch/{batch_id}/zip"

    return {
        "generated": generated,
        "duplicates": duplicates,
        "errors": errors,
        "emails_sent": emails_sent,
        "zip_url": zip_url,
    }


@router.post("/generate", response_model=CertificateGenerateResponse)
def generate_certificate_endpoint(
    payload: CertificateGenerateRequest,
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> CertificateGenerateResponse:
    for field_name, value in payload.model_dump().items():
        if field_name in _OPTIONAL_FIELDS:
            continue
        if not str(value).strip():
            raise HTTPException(400, f"Le champ '{field_name}' est obligatoire.")

    if payload.cert_type not in get_available_types(settings.POSITIONS_FILE):
        raise HTTPException(400, f"Type de certificat inconnu : '{payload.cert_type}'.")

    event_date = normalize_event_date(payload.event_date)
    if event_date is None:
        raise HTTPException(400, f"Date invalide : '{payload.event_date}'.")

    if check_duplicate(payload.name, payload.first_name, payload.event_name, event_date):
        raise HTTPException(409, "Un certificat existe déjà pour cette personne et cet événement.")

    cert_id = secrets.token_hex(16)

    try:
        pdf_path = generate_certificate(
            name=payload.name,
            first_name=payload.first_name,
            event_name=payload.event_name,
            event_date=event_date,
            cert_type=payload.cert_type,
            cert_id=cert_id,
            settings=settings,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, f"Erreur lors de la génération du certificat : {exc}") from exc

    email = payload.email.strip() or None
    email_sent_at = None
    if payload.send_email and email:
        verify_url = f"{settings.BASE_URL}/verifier?code={cert_id}" if settings.BASE_URL else ""
        if send_certificate_email(
            to_email=email,
            name=payload.name,
            first_name=payload.first_name,
            event_name=payload.event_name,
            event_date=event_date,
            pdf_path=pdf_path,
            verify_url=verify_url,
            cert_id=cert_id,
            kind="unitaire",
            sent_by=_current_username(user),
        ):
            email_sent_at = datetime.now(timezone.utc).isoformat()

    cert = {
        "id": cert_id,
        "name": payload.name,
        "first_name": payload.first_name,
        "event_name": payload.event_name,
        "event_date": event_date,
        "cert_type": payload.cert_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": _current_username(user),
        "pdf_path": pdf_path,
        "pdf_checksum": sha256_of_file(pdf_path),
        "email": email,
        "email_sent_at": email_sent_at,
    }

    try:
        insert_certificate(cert)
    except DuplicateCertificateError as exc:
        Path(pdf_path).unlink(missing_ok=True)
        raise HTTPException(409, "Un certificat existe déjà pour cette personne et cet événement.") from exc

    return CertificateGenerateResponse(
        id=cert_id,
        pdf_url=f"/api/certificates/{cert_id}/pdf",
        qr_content=f"{settings.BASE_URL}/verifier?code={cert_id}",
        email_sent=email_sent_at is not None,
    )


@router.post("/batch")
def generate_batch_endpoint(
    file: UploadFile = File(...),
    column_mapping: str = Form(...),
    default_cert_type: str | None = Form(None),
    default_event_name: str | None = Form(None),
    default_event_date: str | None = Form(None),
    send_email: bool = Form(False),
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> dict[str, Any]:
    """Raw Excel + column mapping, no client-side cleaning. Declared as a
    plain `def` (not `async def`) on purpose: everything below is CPU/IO
    bound and synchronous (PDF rendering, disk writes, SQLite); as a plain
    function FastAPI runs it in a worker thread instead of on the shared
    asyncio event loop, so one admin's big batch doesn't freeze /verifier
    and every other request for the whole app in the meantime.
    """
    try:
        mapping: dict[str, str] = json.loads(column_mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Le mapping de colonnes n'est pas un JSON valide.") from exc

    default_event_name = (default_event_name or "").strip() or None
    default_event_date = (default_event_date or "").strip() or None

    missing_mapping = [f for f in REQUIRED_ROW_FIELDS if f not in mapping]
    if "event_name" not in mapping and not default_event_name:
        missing_mapping.append("event_name")
    if "event_date" not in mapping and not default_event_date:
        missing_mapping.append("event_date")
    if missing_mapping:
        raise HTTPException(
            400, f"Colonnes manquantes dans le mapping : {', '.join(missing_mapping)}."
        )

    contents = file.file.read()
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    except Exception as exc:
        raise HTTPException(400, "Impossible de lire le fichier Excel fourni.") from exc

    sheet = workbook.active
    raw_rows = list(sheet.iter_rows(values_only=True))
    if not raw_rows:
        raise HTTPException(400, "Le fichier Excel est vide.")

    header = [str(cell).strip() if cell is not None else "" for cell in raw_rows[0]]
    data_rows = raw_rows[1:]

    def get_field(row_dict: dict[str, Any], field_key: str) -> str | None:
        column_name = mapping.get(field_key)
        if not column_name:
            return None
        value = row_dict.get(column_name)
        if value is None:
            return None
        return str(value).strip() or None

    rows: list[dict[str, Any]] = []
    for row in data_rows:
        row_dict = dict(zip(header, row))
        rows.append(
            {
                "name": get_field(row_dict, "name") or "",
                "first_name": get_field(row_dict, "first_name") or "",
                "event_name": get_field(row_dict, "event_name") or default_event_name or "",
                "event_date": get_field(row_dict, "event_date") or default_event_date or "",
                "cert_type": get_field(row_dict, "cert_type") or default_cert_type or "",
                "email": get_field(row_dict, "email") or "",
            }
        )

    return _generate_from_rows(rows, send_email, settings, user, start_index=2)


@router.post("/batch-rows")
def generate_batch_from_rows_endpoint(
    payload: BatchRowsRequest,
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> dict[str, Any]:
    """Same as /batch, but takes rows the front already resolved/cleaned
    (batch editor grid) instead of an Excel file + column mapping.
    """
    rows = [row.model_dump() for row in payload.rows]
    return _generate_from_rows(rows, payload.send_email, settings, user)


@router.get("/batch/{batch_id}/zip")
def download_batch_zip(
    batch_id: str,
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{16}", batch_id):
        raise HTTPException(400, "Identifiant de batch invalide.")
    zip_path = Path(settings.CERTIFS_DIR) / "_batches" / f"{batch_id}.zip"
    if not zip_path.exists():
        raise HTTPException(404, "Archive de batch introuvable.")
    return FileResponse(path=zip_path, media_type="application/zip", filename=zip_path.name)


@router.get("/{cert_id}/pdf")
def download_certificate_pdf(
    cert_id: str,
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> FileResponse:
    cert = get_certificate_by_id(cert_id)
    if cert is None:
        raise HTTPException(404, "Certificat introuvable.")

    pdf_path = Path(cert["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(404, "Le fichier PDF associé à ce certificat est introuvable sur le serveur.")

    return FileResponse(path=pdf_path, media_type="application/pdf", filename=pdf_path.name)
