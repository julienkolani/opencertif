import html
import logging
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .crypto import decrypt_secret
from .db import get_setting, insert_email_log

logger = logging.getLogger(__name__)

# Built for email clients, not browsers: table layout, inline styles only
# (Gmail and Outlook drop <style> blocks or parts of them), a "bulletproof"
# button made of a coloured table cell, and the raw link repeated below it
# for clients that block buttons. Max width 560px so it reads well on phones.
DEFAULT_EMAIL_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Votre certificat : {evenement}</title>
</head>
<body style="margin:0; padding:0; background-color:#F3F4F6;">
<div style="display:none; max-height:0; overflow:hidden; opacity:0;">Votre certificat pour {evenement} est disponible en pièce jointe.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#F3F4F6" style="background-color:#F3F4F6;">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px; background-color:#FFFFFF; border:1px solid #E5E7EB; border-radius:12px; font-family:Arial, Helvetica, sans-serif; color:#1A1A2E;">
        <tr>
          <td style="height:6px; background-color:#7C3AED; border-radius:12px 12px 0 0; font-size:0; line-height:0;">&nbsp;</td>
        </tr>
        <tr>
          <td style="padding:32px 32px 8px 32px;">
            <p style="margin:0 0 4px 0; font-size:12px; letter-spacing:1px; text-transform:uppercase; color:#7C3AED; font-weight:bold;">Certificat</p>
            <h1 style="margin:0; font-size:22px; line-height:1.3; color:#1A1A2E;">{evenement}</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 32px 0 32px; font-size:15px; line-height:1.6;">
            <p style="margin:0 0 16px 0;">Bonjour {prenom} {nom},</p>
            <p style="margin:0 0 16px 0;">Félicitations&nbsp;! Vous trouverez en pièce jointe votre certificat pour <strong>{evenement}</strong>, en date du {date}.</p>
            <p style="margin:0 0 24px 0;">Chaque certificat porte un QR code unique&nbsp;: toute personne qui le reçoit (employeur, établissement...) peut en vérifier l'authenticité en ligne.</p>
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:0 32px 24px 32px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td bgcolor="#7C3AED" style="background-color:#7C3AED; border-radius:8px;">
                  <a href="{url_verification}" target="_blank" style="display:inline-block; padding:12px 28px; font-family:Arial, Helvetica, sans-serif; font-size:15px; font-weight:bold; color:#FFFFFF; text-decoration:none; border-radius:8px;">Vérifier mon certificat</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:0 32px 24px 32px; font-size:13px; line-height:1.5; color:#6B7280;">
            Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur&nbsp;:<br>
            <a href="{url_verification}" target="_blank" style="color:#7C3AED; word-break:break-all;">{url_verification}</a>
          </td>
        </tr>
        <tr>
          <td style="padding:0 32px 32px 32px; font-size:15px; line-height:1.6;">
            <p style="margin:0;">Cordialement,<br>L'équipe organisatrice</p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 32px; border-top:1px solid #E5E7EB; font-size:12px; line-height:1.5; color:#9CA3AF;">
            Cet e-mail a été envoyé automatiquement. Pour toute question ou erreur sur votre certificat, répondez simplement à ce message.
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

DEFAULT_EMAIL_SUBJECT = "Votre certificat : {evenement}"

# Only these placeholders are substituted. Anything else between braces
# (CSS in a <style> block, inline JSON...) is left untouched, so a custom
# template can never fail to render. str.format() used to raise on such
# braces, and the code then silently sent the default template instead.
TEMPLATE_VARIABLES = ("prenom", "nom", "evenement", "date", "url_verification")
_PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(TEMPLATE_VARIABLES) + r")\}")

# Sample values used by the preview and by the test email.
SAMPLE_VALUES = {
    "prenom": "Jean",
    "nom": "Dupont",
    "evenement": "Formation Python",
    "date": "01/01/2026",
    "url_verification": "https://exemple.com/verifier?code=12345",
}


def render_template(template: str, values: dict[str, str], escape_html: bool = True) -> str:
    """Replaces {prenom}, {nom}, {evenement}, {date} and {url_verification}.

    Values are HTML-escaped by default (a participant name coming from an
    Excel file must not inject markup into the email body); pass
    escape_html=False for the plain-text subject line.
    """
    def replace(match: re.Match) -> str:
        value = str(values.get(match.group(1), ""))
        return html.escape(value) if escape_html else value

    return _PLACEHOLDER_RE.sub(replace, template)


def build_email_content(
    values: dict[str, str],
    template: str | None = None,
    subject_template: str | None = None,
) -> tuple[str, str]:
    """Returns (subject, html_body).

    template / subject_template default to the saved settings, then to the
    built-in defaults. The preview and the test email pass the values being
    edited in the UI, so they can be checked before saving.
    """
    template = template or get_setting("smtp_email_template") or DEFAULT_EMAIL_TEMPLATE
    subject_template = subject_template or get_setting("smtp_email_subject") or DEFAULT_EMAIL_SUBJECT
    subject = render_template(subject_template, values, escape_html=False)
    return subject, render_template(template, values)


def _get_smtp_params() -> dict:
    """Retourne les paramètres SMTP depuis la table settings (priorité) puis les variables d'env."""
    import os
    return {
        "host": get_setting("smtp_host") or os.getenv("SMTP_HOST", ""),
        "port": int(get_setting("smtp_port") or os.getenv("SMTP_PORT", "587")),
        "user": get_setting("smtp_user") or os.getenv("SMTP_USER", ""),
        "password": decrypt_secret(get_setting("smtp_password") or os.getenv("SMTP_PASSWORD", "")),
        "from_addr": get_setting("smtp_from") or os.getenv("SMTP_FROM", ""),
        "security": get_setting("smtp_security") or "starttls",  # starttls | ssl | none
    }


def _build_smtp_connection(params: dict):
    """Ouvre et retourne une connexion SMTP selon le mode de sécurité."""
    security = params["security"].lower()
    if security == "ssl":
        context = ssl.create_default_context()
        server = smtplib.SMTP_SSL(params["host"], params["port"], context=context, timeout=10)
    else:
        server = smtplib.SMTP(params["host"], params["port"], timeout=10)
        if security == "starttls":
            server.starttls(ssl.create_default_context())
    if params["user"]:
        server.login(params["user"], params["password"])
    return server


def test_smtp_connection() -> tuple[bool, str]:
    """Teste la connexion SMTP avec les paramètres actuels.
    Retourne (True, message_ok) ou (False, message_erreur).
    """
    params = _get_smtp_params()
    if not params["host"]:
        return False, "Hôte SMTP non configuré."
    try:
        with _build_smtp_connection(params) as server:
            server.noop()
        return True, f"Connexion réussie à {params['host']}:{params['port']} ({params['security']})."
    except (smtplib.SMTPException, OSError) as exc:
        return False, f"Échec de connexion : {exc}"


def record_email(
    recipient: str,
    subject: str | None,
    kind: str,
    status: str,
    error: str | None = None,
    html_body: str | None = None,
    cert_id: str | None = None,
    event_name: str | None = None,
    sent_by: str | None = None,
) -> None:
    """Adds a row to the email_log table. Never raises: failing to write the
    journal must not turn a delivered email into an error for the caller."""
    try:
        insert_email_log({
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "recipient": recipient,
            "subject": subject,
            "cert_id": cert_id,
            "event_name": event_name,
            "kind": kind,
            "status": status,
            "error": error,
            "sent_by": sent_by,
            "html_body": html_body,
        })
    except Exception:
        logger.exception("Impossible d'écrire le journal d'envoi pour %s", recipient)


def send_certificate_email(
    to_email: str,
    name: str,
    first_name: str,
    event_name: str,
    event_date: str,
    pdf_path: str,
    verify_url: str = "",
    cert_id: str | None = None,
    kind: str = "unitaire",
    sent_by: str | None = None,
) -> bool:
    """Envoie le certificat PDF par email. Retourne True si succès.

    Every attempt, successful or not, is recorded in email_log (kind is
    "unitaire", "batch" or "masse"; sent_by is the admin who triggered it).
    """
    params = _get_smtp_params()
    subject, html_body = build_email_content({
        "prenom": first_name,
        "nom": name,
        "evenement": event_name,
        "date": event_date,
        "url_verification": verify_url,
    })

    def log(status: str, error: str | None = None) -> None:
        record_email(
            to_email, subject, kind, status, error, html_body,
            cert_id=cert_id, event_name=event_name, sent_by=sent_by,
        )

    if not params["host"] or not params["from_addr"]:
        logger.warning("SMTP non configuré, email non envoyé.")
        log("echec", "SMTP non configuré (hôte ou adresse expéditeur manquant).")
        return False

    message = MIMEMultipart("mixed")
    message["Subject"] = subject
    message["From"] = params["from_addr"]
    message["To"] = to_email
    message.attach(MIMEText(html_body, "html"))

    try:
        pdf_bytes = Path(pdf_path).read_bytes()
    except OSError as exc:
        logger.exception("Impossible de lire le PDF %s", pdf_path)
        log("echec", f"PDF illisible : {exc}")
        return False

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=Path(pdf_path).name)
    message.attach(attachment)

    try:
        with _build_smtp_connection(params) as server:
            server.sendmail(params["from_addr"], [to_email], message.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Échec d'envoi à %s", to_email)
        log("echec", f"Erreur SMTP : {exc}")
        return False

    log("envoye")
    return True
