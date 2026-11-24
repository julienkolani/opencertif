from typing import Any

from fastapi import APIRouter, Depends, Query

from core.auth import require_any_role
from core.db import list_certificates

router = APIRouter()


@router.get("")
def get_history(
    search: str | None = Query(None),
    cert_type: str | None = Query(None),
    year: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    user: dict[str, Any] = Depends(require_any_role(["certifs-admin", "certifs-viewer"])),
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if search:
        filters["search"] = search
    if cert_type:
        filters["cert_type"] = cert_type
    if year:
        filters["year"] = year

    items, total = list_certificates(filters=filters, page=page, per_page=per_page)

    return {"items": items, "total": total, "page": page, "per_page": per_page}
