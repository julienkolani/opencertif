import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.BASE_URL = os.getenv("BASE_URL", "")
        self.DEV_MODE = os.getenv("DEV_MODE", "false").strip().lower() in ("1", "true", "yes")
        self.CORS_ORIGINS = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "*").split(",")
            if origin.strip()
        ]
        self.DB_PATH = os.getenv("DB_PATH", "data/certificates.db")
        self.TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "data/templates")
        self.CERTIFS_DIR = os.getenv("CERTIFS_DIR", "data/certifs")
        self.POSITIONS_FILE = os.getenv("POSITIONS_FILE", "data/template_positions.json")

        self.KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "")
        self.KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "")
        self.KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "")
        self.KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

        # Journal des emails : entrées de plus de N jours supprimées (au plus
        # une fois par jour). 0 = conservation illimitée (défaut).
        self.EMAIL_LOG_RETENTION_DAYS = int(os.getenv("EMAIL_LOG_RETENTION_DAYS", "0") or 0)

        self.SMTP_HOST = os.getenv("SMTP_HOST", "")
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USER = os.getenv("SMTP_USER", "")
        self.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
        self.SMTP_FROM = os.getenv("SMTP_FROM", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()

def get_smtp_config_dict() -> dict:
    """Retourne la config SMTP depuis la table settings (priorité) puis les variables d'env.
    N'est pas mise en cache car modifiable depuis l'UI.
    """
    from core.db import get_setting
    import os
    return {
        "host": get_setting("smtp_host") or os.getenv("SMTP_HOST", ""),
        "port": int(get_setting("smtp_port") or os.getenv("SMTP_PORT", "587")),
        "user": get_setting("smtp_user") or os.getenv("SMTP_USER", ""),
        "from_addr": get_setting("smtp_from") or os.getenv("SMTP_FROM", ""),
        "security": get_setting("smtp_security") or "starttls",
        "email_subject": get_setting("smtp_email_subject") or "Votre certificat : {evenement}",
        "email_template": get_setting("smtp_email_template") or "",
    }
