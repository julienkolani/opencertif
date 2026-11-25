import logging
import smtplib
import threading
from datetime import datetime, timezone
from typing import Any


from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_role
from core.config import get_settings, get_smtp_config_dict
from core.crypto import encrypt_secret
from core.db import get_certificates_for_email, mark_email_sent, set_setting
from core.mailer import (
    SAMPLE_VALUES,
    _build_smtp_connection,
    _get_smtp_params,
    build_email_content,
    send_certificate_email,
    test_smtp_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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
        msg["Subject"] = f"[Test] {subject}"
        msg["From"] = params["from_addr"]
        msg["To"] = payload.to_email
        with _build_smtp_connection(params) as server:
            server.sendmail(params["from_addr"], [payload.to_email], msg.as_string())
        return {"ok": True, "message": "Connexion OK et email de test envoyé."}
    except Exception as exc:
        return {"ok": False, "message": f"Connexion OK mais échec de l'envoi du test : {exc}"}

_send_jobs: dict[str, dict] = {}
_send_jobs_lock = threading.Lock()

def _do_send_emails(job_id: str, certs: list, base_url: str) -> None:
    """Tâche d'arrière-plan : envoie les emails et met à jour le job."""
    sent = skipped = 0
    errors = []
    for cert in certs:
        if not cert.get("email"):
            skipped += 1
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
        )
        if success:
            mark_email_sent(cert["id"], datetime.now(timezone.utc).isoformat())
            sent += 1
            logger.info("Email envoyé à %s (cert %s)", cert["email"], cert["id"])
        else:
            errors.append({"cert_id": cert["id"], "email": cert["email"], "reason": "Échec SMTP"})
    with _send_jobs_lock:
        _send_jobs[job_id].update({
            "status": "done",
            "result": {"total": len(certs), "sent": sent, "skipped": skipped, "errors": errors},
        })

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
    with _send_jobs_lock:
        _send_jobs[job_id] = {"status": "running", "total": len(certs), "result": None}
    background_tasks.add_task(_do_send_emails, job_id, certs, settings.BASE_URL)
    return {"job_id": job_id, "total": len(certs), "status": "running"}

@router.get("/send/{job_id}")
def get_send_job(
    job_id: str,
    user: dict = Depends(require_role("certifs-admin")),
) -> dict:
    """Retourne l'état d'un job d'envoi d'emails."""
    with _send_jobs_lock:
        job = _send_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job d'envoi introuvable.")
    return {"job_id": job_id, **job}

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
