import os
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

from core.auth import require_role
from core.certgen import get_available_types, load_template_positions, render_preview, save_template_positions
from core.config import Settings, get_settings

router = APIRouter()

_SAFE_CERT_TYPE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class PositionXY(BaseModel):
    x: float
    y: float


class TemplateTypeConfig(BaseModel):
    template_file: str
    name_position: PositionXY
    name_font: str
    name_max_size: int
    name_min_size: int
    name_max_width: float
    qr_position: PositionXY
    qr_size: int
    pages: int
    name_page: int



@router.post("")
def create_template(
    cert_type: str = Form(..., min_length=1),
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> dict[str, Any]:
    if not _SAFE_CERT_TYPE_RE.fullmatch(cert_type):
        raise HTTPException(
            400, "L'identifiant ne doit contenir que lettres, chiffres, '-' et '_'."
        )

    positions = load_template_positions(settings.POSITIONS_FILE)
    if cert_type in positions:
        raise HTTPException(400, f"Le modèle '{cert_type}' existe déjà.")

    # Path(...).name strips any directory component a crafted filename could
    # smuggle in (e.g. "../../etc/foo.pdf"); cert_type is already restricted
    # to a safe slug above, so the final path can't escape TEMPLATES_DIR.
    original_name = Path(file.filename or "").name
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(400, "Le fichier doit être un PDF.")

    filename = f"{cert_type}_{original_name}"
    file_path = Path(settings.TEMPLATES_DIR) / filename

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    positions[cert_type] = {
        "template_file": filename,
        "name_position": {"x": 200, "y": 400},
        "name_font": "Helvetica-Bold",
        "name_max_size": 24,
        "name_min_size": 12,
        "name_max_width": 200,
        "qr_position": {"x": 50, "y": 50},
        "qr_size": 100,
        "pages": 1,
        "name_page": 1,
    }
    save_template_positions(settings.POSITIONS_FILE, positions)
    return positions[cert_type]

@router.delete("/{cert_type}")
def delete_template(
    cert_type: str,
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> dict[str, Any]:
    positions = load_template_positions(settings.POSITIONS_FILE)
    if cert_type not in positions:
        raise HTTPException(404, f"Modèle '{cert_type}' introuvable.")
        
    config = positions.pop(cert_type)
    save_template_positions(settings.POSITIONS_FILE, positions)
    
    filename = config.get("template_file")
    if filename:
        is_used = any(t.get("template_file") == filename for t in positions.values())
        if not is_used:
            file_path = Path(settings.TEMPLATES_DIR) / filename
            if file_path.exists():
                os.remove(file_path)
                
    return {"ok": True}

@router.get("")
def list_types(
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> dict[str, Any]:
    return {"types": get_available_types(settings.POSITIONS_FILE)}


@router.get("/{cert_type}")
def get_type(
    cert_type: str,
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> dict[str, Any]:
    positions = load_template_positions(settings.POSITIONS_FILE)
    if cert_type not in positions:
        raise HTTPException(404, f"Type de certificat inconnu : '{cert_type}'.")
    return positions[cert_type]


@router.put("/{cert_type}")
def update_type(
    cert_type: str,
    payload: TemplateTypeConfig,
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> dict[str, Any]:
    positions = load_template_positions(settings.POSITIONS_FILE)
    positions[cert_type] = payload.model_dump()
    save_template_positions(settings.POSITIONS_FILE, positions)
    return positions[cert_type]


@router.get("/{cert_type}/preview")
def preview_type(
    cert_type: str,
    test_name: str = Query(..., min_length=1),
    x: float | None = Query(None, description="Override name_position.x (not persisted)"),
    y: float | None = Query(None, description="Override name_position.y (not persisted)"),
    name_max_size: int | None = Query(None),
    name_min_size: int | None = Query(None),
    name_max_width: float | None = Query(None),
    qr_x: float | None = Query(None, description="Override qr_position.x (not persisted)"),
    qr_y: float | None = Query(None, description="Override qr_position.y (not persisted)"),
    qr_size: int | None = Query(None),
    settings: Settings = Depends(get_settings),
    user: dict[str, Any] = Depends(require_role("certifs-admin")),
) -> Response:
    if cert_type not in get_available_types(settings.POSITIONS_FILE):
        raise HTTPException(404, f"Type de certificat inconnu : '{cert_type}'.")

    overrides: dict[str, Any] = {}
    if x is not None or y is not None:
        name_position: dict[str, float] = {}
        if x is not None:
            name_position["x"] = x
        if y is not None:
            name_position["y"] = y
        overrides["name_position"] = name_position
    if name_max_size is not None:
        overrides["name_max_size"] = name_max_size
    if name_min_size is not None:
        overrides["name_min_size"] = name_min_size
    if name_max_width is not None:
        overrides["name_max_width"] = name_max_width
    if qr_x is not None or qr_y is not None:
        qr_position: dict[str, float] = {}
        if qr_x is not None:
            qr_position["x"] = qr_x
        if qr_y is not None:
            qr_position["y"] = qr_y
        overrides["qr_position"] = qr_position
    if qr_size is not None:
        overrides["qr_size"] = qr_size

    try:
        image_bytes = render_preview(cert_type, test_name, settings, overrides=overrides or None)
    except FileNotFoundError as exc:
        raise HTTPException(
            404, "Le fichier de template PDF est introuvable sur le serveur."
        ) from exc

    return Response(content=image_bytes, media_type="image/png")
