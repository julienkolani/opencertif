from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from core.db import get_certificate_by_checksum, get_certificate_by_id
from core.utils import sha256_of_bytes

router = APIRouter()

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 Mo

def _public_details(cert: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": cert["id"],
        "name": cert["name"],
        "first_name": cert["first_name"],
        "event_name": cert["event_name"],
        "event_date": cert["event_date"],
        "cert_type": cert["cert_type"],
        "generated_at": cert["generated_at"],
    }


@router.get("/{code}")
def verify_by_code(code: str) -> dict[str, Any]:
    cert = get_certificate_by_id(code)
    if cert is None:
        raise HTTPException(404, "Certificat introuvable.")

    return {"status": "authentique", "details": _public_details(cert)}


@router.post("/file")
async def verify_by_file(file: UploadFile = File(...)) -> dict[str, Any]:
    contents = await file.read(_MAX_FILE_SIZE + 1)
    if len(contents) > _MAX_FILE_SIZE:
        raise HTTPException(413, "Fichier trop volumineux (maximum 50 Mo).")
    checksum = sha256_of_bytes(contents)

    cert = get_certificate_by_checksum(checksum)
    if cert is None:
        return {
            "status": "altere_ou_inconnu",
            "message": "Fichier non reconnu ou altéré.",
        }

    return {
        "status": "authentique",
        "message": "Fichier authentique et non altéré.",
        "details": _public_details(cert),
    }
