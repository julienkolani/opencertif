import logging
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .crypto import decrypt_secret
from .db import get_setting

logger = logging.getLogger(__name__)

DEFAULT_EMAIL_TEMPLATE = """<html>
<body>
  <p>Bonjour {prenom} {nom},</p>
  <p>Félicitations ! Votre certificat pour <strong>{evenement}</strong>
  (le {date}) est disponible en pièce jointe de cet e-mail.</p>
  <p>Vous pouvez vérifier l'authenticité de votre certificat à l'adresse :<br>
  <a href="{url_verification}">{url_verification}</a></p>
  <p>Cordialement,<br>L'équipe organisatrice</p>
</body>
</html>"""


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


def send_certificate_email(
    to_email: str,
    name: str,
    first_name: str,
    event_name: str,
    event_date: str,
    pdf_path: str,
    verify_url: str = "",
) -> bool:
    """Envoie le certificat PDF par email. Retourne True si succès."""
    params = _get_smtp_params()
    if not params["host"] or not params["from_addr"]:
        logger.warning("SMTP non configuré, email non envoyé.")
        return False

    template = get_setting("smtp_email_template") or DEFAULT_EMAIL_TEMPLATE
    try:
        html_body = template.format(
            prenom=first_name,
            nom=name,
            evenement=event_name,
            date=event_date,
            url_verification=verify_url,
        )
    except (KeyError, ValueError) as exc:
        logger.error("Template email invalide (%s), fallback sur le template par défaut.", exc)
        html_body = DEFAULT_EMAIL_TEMPLATE.format(
            prenom=first_name,
            nom=name,
            evenement=event_name,
            date=event_date,
            url_verification=verify_url,
        )

    subject = get_setting("smtp_email_subject") or f"Votre certificat : {event_name}"

    message = MIMEMultipart("mixed")
    message["Subject"] = subject.format(evenement=event_name)
    message["From"] = params["from_addr"]
    message["To"] = to_email
    message.attach(MIMEText(html_body, "html"))

    try:
        pdf_bytes = Path(pdf_path).read_bytes()
    except OSError:
        logger.exception("Impossible de lire le PDF %s", pdf_path)
        return False

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=Path(pdf_path).name)
    message.attach(attachment)

    try:
        with _build_smtp_connection(params) as server:
            server.sendmail(params["from_addr"], [to_email], message.as_string())
        return True
    except (smtplib.SMTPException, OSError):
        logger.exception("Échec d'envoi à %s", to_email)
        return False
