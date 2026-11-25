import csv
import io
import logging
import smtplib
from datetime import datetime, timezone
from typing import Any, Literal


from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from core.auth import require_role
from core.config import get_settings, get_smtp_config_dict
from core.crypto import encrypt_secret
from core.db import (
    EMAIL_LOG_KINDS,
    EMAIL_LOG_STATUSES,
    create_send_job,
    get_send_job as db_get_send_job,
    update_send_job,
    get_certificates_for_email,
    get_email_log,
    list_email_log,
    mark_email_sent,
    set_setting,
)
from core.mailer import (
    SAMPLE_VALUES,
    _build_smtp_connection,
    _get_smtp_params,
    build_email_content,
    record_email,
    send_certificate_email,
    test_smtp_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _username(user: dict[str, Any]) -> str | None:
    return user.get("preferred_username") or user.get("email") or user.get("sub")


class SmtpConfigRequest(BaseModel):
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    from_addr: str = ""
    security: str = "starttls"
    email_subject: str = "Votre certificat : {evenement}"
    email_template: str = ""

class TemplateOverride(BaseModel):
    """Template being edited in the UI, not saved yet. Empty means: use the
    saved settings, then the built-in default."""
    email_subject: str | None = None
    email_template: str | None = None


class EmailTestRequest(TemplateOverride):
    to_email: str

class EmailSendRequest(BaseModel):
    cert_ids: list[str] | None = None
    event_name: str | None = None
    cert_type: str | None = None
    year: str | None = None
    only_unsent: bool = True
    force_resend: bool = False

@router.get("/config")
def get_config(user: dict = Depends(require_role("certifs-admin"))) -> dict:
    config = get_smtp_config_dict()
    config["configured"] = bool(config["host"])
    return config

@router.post("/config")
def update_config(payload: SmtpConfigRequest, user: dict = Depends(require_role("certifs-admin"))):
    set_setting("smtp_host", payload.host)
    set_setting("smtp_port", str(payload.port))
    set_setting("smtp_user", payload.user)
    if payload.password:
        set_setting("smtp_password", encrypt_secret(payload.password))
    set_setting("smtp_from", payload.from_addr)
    set_setting("smtp_security", payload.security)
    set_setting("smtp_email_subject", payload.email_subject)
    set_setting("smtp_email_template", payload.email_template)
    return {"ok": True}

@router.post("/test")
def test_config(payload: EmailTestRequest, user: dict = Depends(require_role("certifs-admin"))):
    ok, message = test_smtp_connection()
    if not ok:
        return {"ok": False, "message": message}
    
    try:
        from email.mime.text import MIMEText
        params = _get_smtp_params()
        # Same rendering as a real certificate email (sample participant, no
        # PDF attached), so the test shows what recipients will receive.
        subject, html_body = build_email_content(
            SAMPLE_VALUES, payload.email_template, payload.email_subject
        )
        msg = MIMEText(html_body, "html", "utf-8")
        subject = f"[Test] {subject}"
        msg["Subject"] = subject
        msg["From"] = params["from_addr"]
        msg["To"] = payload.to_email
        with _build_smtp_connection(params) as server:
            server.sendmail(params["from_addr"], [payload.to_email], msg.as_string())
    except Exception as exc:
        record_email(payload.to_email, subject, "test", "echec", f"Erreur SMTP : {exc}",
                     html_body, sent_by=_username(user))
        return {"ok": False, "message": f"Connexion OK mais échec de l'envoi du test : {exc}"}
    record_email(payload.to_email, subject, "test", "envoye", None, html_body, sent_by=_username(user))
    return {"ok": True, "message": "Connexion OK et email de test envoyé."}

def _do_send_emails(job_id: str, certs: list, base_url: str, sent_by: str | None = None) -> None:
    """Tâche d'arrière-plan : envoie les emails et met à jour le job en base
    (progression après chaque certificat, résultat à la fin)."""
    try:
        _send_all(job_id, certs, base_url, sent_by)
    except Exception:
        logger.exception("Envoi en masse %s interrompu par une erreur", job_id)
        update_send_job(job_id, status="error")


def _send_all(job_id: str, certs: list, base_url: str, sent_by: str | None) -> None:
    sent = skipped = 0
    errors = []
    for processed, cert in enumerate(certs, start=1):
        if not cert.get("email"):
            skipped += 1
            update_send_job(job_id, processed=processed)
            continue
        verify_url = f"{base_url}/verifier?code={cert['id']}" if base_url else ""
        success = send_certificate_email(
            to_email=cert["email"],
            name=cert["name"],
            first_name=cert["first_name"],
            event_name=cert["event_name"],
            event_date=cert["event_date"],
            pdf_path=cert["pdf_path"],
            verify_url=verify_url,
            cert_id=cert["id"],
            kind="masse",
            sent_by=sent_by,
        )
        if success:
            mark_email_sent(cert["id"], datetime.now(timezone.utc).isoformat())
            sent += 1
            logger.info("Email envoyé à %s (cert %s)", cert["email"], cert["id"])
        else:
            errors.append({
                "cert_id": cert["id"],
                "email": cert["email"],
                "reason": "Échec d'envoi (détail dans le journal des envois)",
            })
        update_send_job(job_id, processed=processed)
    update_send_job(
        job_id,
        status="done",
        result={"total": len(certs), "sent": sent, "skipped": skipped, "errors": errors},
    )

@router.post("/send")
def send_emails(
    payload: EmailSendRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_role("certifs-admin")),
) -> dict:
    """Lance l'envoi d'emails en arrière-plan (max 500 par appel). Retourne un job_id."""
    import secrets as _sec
    certs = get_certificates_for_email(
        cert_ids=payload.cert_ids,
        event_name=payload.event_name,
        cert_type=payload.cert_type,
        year=payload.year,
        only_unsent=payload.only_unsent and not payload.force_resend,
        limit=500,
    )
    settings = get_settings()
    job_id = _sec.token_hex(8)
    create_send_job(job_id, len(certs), _username(user))
    background_tasks.add_task(_do_send_emails, job_id, certs, settings.BASE_URL, _username(user))
    return {"job_id": job_id, "total": len(certs), "status": "running"}

@router.get("/send/{job_id}")
def get_send_job(
    job_id: str,
    user: dict = Depends(require_role("certifs-admin")),
) -> dict:
    """État d'un envoi en masse : running, done, interrupted (API redémarrée
    pendant l'envoi) ou error, avec la progression (processed / total)."""
    job = db_get_send_job(job_id)
    if job is None:
        raise HTTPException(404, "Job d'envoi introuvable.")
    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job["total"],
        "processed": job["processed"],
        "result": job["result"],
    }

@router.get("/preview")
def preview_email(user: dict = Depends(require_role("certifs-admin"))):
    """Preview of the saved template."""
    subject, html = build_email_content(SAMPLE_VALUES)
    return {"subject": subject, "html": html}


@router.post("/preview")
def preview_email_draft(payload: TemplateOverride, user: dict = Depends(require_role("certifs-admin"))):
    """Preview of the template being edited (falls back to the saved one)."""
    subject, html = build_email_content(SAMPLE_VALUES, payload.email_template, payload.email_subject)
    return {"subject": subject, "html": html}


# --- Journal des envois ----------------------------------------------------

def _log_filters(
    recipient: str | None = None,
    event_name: str | None = None,
    status: Literal[EMAIL_LOG_STATUSES] | None = None,  # type: ignore[valid-type]
    kind: Literal[EMAIL_LOG_KINDS] | None = None,  # type: ignore[valid-type]
) -> dict[str, str | None]:
    return {"recipient": recipient, "event_name": event_name, "status": status, "kind": kind}


@router.get("/log")
def get_email_log_page(
    filters: dict = Depends(_log_filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: dict = Depends(require_role("certifs-admin")),
) -> dict:
    """Every send attempt, newest first (without the HTML body)."""
    items, total = list_email_log(**filters, limit=page_size, offset=(page - 1) * page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/log/export.csv")
def export_email_log(
    filters: dict = Depends(_log_filters),
    user: dict = Depends(require_role("certifs-admin")),
) -> Response:
    items, _total = list_email_log(**filters, limit=None)
    columns = ["sent_at", "recipient", "subject", "event_name", "cert_id", "kind", "status", "error", "sent_by"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", delimiter=";")
    writer.writeheader()
    writer.writerows(items)
    # UTF-8 BOM so Excel opens accents correctly.
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="journal-emails.csv"'},
    )


@router.get("/log/{log_id}")
def get_email_log_entry(log_id: int, user: dict = Depends(require_role("certifs-admin"))) -> dict:
    """One entry, including the exact HTML that was sent."""
    entry = get_email_log(log_id)
    if entry is None:
        raise HTTPException(404, "Entrée du journal introuvable.")
    return entry

