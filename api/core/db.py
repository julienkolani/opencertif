import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS certificates (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    first_name      TEXT NOT NULL,
    event_name      TEXT NOT NULL,
    event_date      TEXT NOT NULL,
    cert_type       TEXT NOT NULL,
    generated_at    TEXT NOT NULL,
    generated_by    TEXT,
    pdf_path        TEXT NOT NULL,
    pdf_checksum    TEXT NOT NULL,
    email           TEXT,
    email_sent_at   TEXT
)
"""

CREATE_TABLE_SETTINGS_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

# One row per send attempt (success or failure), kept for later checks:
# OpenCertif sends through SMTP, which never stores a copy in the sender's
# mailbox, so this table is the only record of what was sent to whom.
CREATE_TABLE_EMAIL_LOG_SQL = """
CREATE TABLE IF NOT EXISTS email_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at     TEXT NOT NULL,
    recipient   TEXT NOT NULL,
    subject     TEXT,
    cert_id     TEXT,
    event_name  TEXT,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    error       TEXT,
    sent_by     TEXT,
    html_body   TEXT
)
"""

EMAIL_LOG_KINDS = ("unitaire", "batch", "masse", "test")
EMAIL_LOG_STATUSES = ("envoye", "echec")

CREATE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup
    ON certificates(name, first_name, event_name, event_date)
"""


class DuplicateCertificateError(Exception):
    """Raised when a certificate already exists for (name, first_name, event_name, event_date)."""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    # timeout: a writer waits up to 30 s for another one to finish instead of
    # failing after the 5 s default with "database is locked" (e.g. a batch
    # generation while a mass email send updates email_sent_at/email_log).
    conn = sqlite3.connect(settings.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    settings = get_settings()
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        # WAL: readers no longer block on a writer (public verification stays
        # responsive during a batch). Persistent: stored in the database file.
        # Side files certificates.db-wal / -shm appear next to it, so copying
        # the .db file alone is NOT a valid backup: use deploy/backup.sh.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_TABLE_SETTINGS_SQL)
        conn.execute(CREATE_INDEX_SQL)
        conn.execute(CREATE_TABLE_EMAIL_LOG_SQL)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_log_sent_at ON email_log(sent_at)")
        
        # Migration : colonne email
        try:
            conn.execute("ALTER TABLE certificates ADD COLUMN email TEXT")
        except sqlite3.OperationalError:
            pass


def insert_certificate(cert: dict[str, Any]) -> None:
    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO certificates (
                    id, name, first_name, event_name, event_date, cert_type,
                    generated_at, generated_by, pdf_path, pdf_checksum, email, email_sent_at
                ) VALUES (
                    :id, :name, :first_name, :event_name, :event_date, :cert_type,
                    :generated_at, :generated_by, :pdf_path, :pdf_checksum, :email, :email_sent_at
                )
                """,
                {
                    "id": cert["id"],
                    "name": cert["name"],
                    "first_name": cert["first_name"],
                    "event_name": cert["event_name"],
                    "event_date": cert["event_date"],
                    "cert_type": cert["cert_type"],
                    "generated_at": cert["generated_at"],
                    "generated_by": cert.get("generated_by"),
                    "pdf_path": cert["pdf_path"],
                    "pdf_checksum": cert["pdf_checksum"],
                    "email": cert.get("email"),
                    "email_sent_at": cert.get("email_sent_at"),
                },
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateCertificateError(
                f"Certificate already exists for {cert['name']} {cert['first_name']} "
                f"/ {cert['event_name']} / {cert['event_date']}"
            ) from exc


def get_certificate_by_id(cert_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM certificates WHERE id = ?", (cert_id,)
        ).fetchone()
        return dict(row) if row else None


def get_certificate_by_checksum(checksum: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM certificates WHERE pdf_checksum = ?", (checksum,)
        ).fetchone()
        return dict(row) if row else None


def check_duplicate(name: str, first_name: str, event_name: str, event_date: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM certificates
            WHERE name = ? AND first_name = ? AND event_name = ? AND event_date = ?
            """,
            (name, first_name, event_name, event_date),
        ).fetchone()
        return row is not None


def list_certificates(
    filters: dict[str, Any] | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    filters = filters or {}
    where_clauses: list[str] = []
    params: list[Any] = []

    search = filters.get("search")
    if search:
        where_clauses.append("(name LIKE ? OR first_name LIKE ? OR event_name LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    cert_type = filters.get("cert_type")
    if cert_type:
        where_clauses.append("cert_type = ?")
        params.append(cert_type)

    year = filters.get("year")
    if year:
        where_clauses.append("event_date LIKE ?")
        params.append(f"{year}-%")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM certificates {where_sql}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""
            SELECT * FROM certificates
            {where_sql}
            ORDER BY generated_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()

        return [dict(row) for row in rows], total


def get_setting(key: str, default: str = "") -> str:
    """Lit une valeur depuis la table settings."""
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

def set_setting(key: str, value: str) -> None:
    """Ecrit ou met à jour une clé dans la table settings."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

def get_certificates_for_email(
    cert_ids: list[str] | None = None,
    event_name: str | None = None,
    cert_type: str | None = None,
    year: str | None = None,
    only_unsent: bool = True,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Retourne les certificats correspondant aux filtres pour envoi email.
    Si only_unsent=True, ne retourne que ceux sans email_sent_at.
    Ne retourne que les lignes ayant une adresse email.
    """
    where_clauses: list[str] = ["email IS NOT NULL AND email != ''"]
    params: list[Any] = []

    if cert_ids:
        placeholders = ",".join("?" for _ in cert_ids)
        where_clauses.append(f"id IN ({placeholders})")
        params.extend(cert_ids)
    
    if event_name:
        where_clauses.append("event_name = ?")
        params.append(event_name)
        
    if cert_type:
        where_clauses.append("cert_type = ?")
        params.append(cert_type)
        
    if year:
        where_clauses.append("event_date LIKE ?")
        params.append(f"{year}-%")
        
    if only_unsent:
        where_clauses.append("email_sent_at IS NULL")

    where_sql = f"WHERE {' AND '.join(where_clauses)}"

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM certificates {where_sql} LIMIT ?", (*params, limit)
        ).fetchall()
        return [dict(row) for row in rows]

def mark_email_sent(cert_id: str, sent_at: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE certificates SET email_sent_at = ? WHERE id = ?",
            (sent_at, cert_id),
        )


_EMAIL_LOG_LIST_COLUMNS = (
    "id, sent_at, recipient, subject, cert_id, event_name, kind, status, error, sent_by"
)


def insert_email_log(entry: dict[str, Any]) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO email_log (
                sent_at, recipient, subject, cert_id, event_name,
                kind, status, error, sent_by, html_body
            ) VALUES (
                :sent_at, :recipient, :subject, :cert_id, :event_name,
                :kind, :status, :error, :sent_by, :html_body
            )
            """,
            {
                "sent_at": entry["sent_at"],
                "recipient": entry["recipient"],
                "subject": entry.get("subject"),
                "cert_id": entry.get("cert_id"),
                "event_name": entry.get("event_name"),
                "kind": entry["kind"],
                "status": entry["status"],
                "error": entry.get("error"),
                "sent_by": entry.get("sent_by"),
                "html_body": entry.get("html_body"),
            },
        )
        return int(cursor.lastrowid)


def _email_log_where(
    recipient: str | None, event_name: str | None, status: str | None, kind: str | None
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if recipient:
        clauses.append("recipient LIKE ?")
        params.append(f"%{recipient}%")
    if event_name:
        clauses.append("event_name LIKE ?")
        params.append(f"%{event_name}%")
    if status:
        clauses.append("status = ?")
        params.append(status)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


def list_email_log(
    recipient: str | None = None,
    event_name: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int | None = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Newest first, without the HTML body (see get_email_log). limit=None
    returns every matching row (CSV export)."""
    where_sql, params = _email_log_where(recipient, event_name, status, kind)
    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM email_log {where_sql}", params).fetchone()[0]
        sql = f"SELECT {_EMAIL_LOG_LIST_COLUMNS} FROM email_log {where_sql} ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, limit, offset]
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows], int(total)


def get_email_log(log_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM email_log WHERE id = ?", (log_id,)).fetchone()
        return dict(row) if row else None
