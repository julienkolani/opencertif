import hashlib
from datetime import date, datetime

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: str, chunk_size: int = 8192) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_event_date(value: object) -> str | None:
    """Return an ISO 'YYYY-MM-DD' string, or None if unparseable.

    Excel cells for a date column commonly arrive as datetime/date objects
    (via openpyxl) or as plain strings in a locale-specific format.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        value = value.strip()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
    return None
