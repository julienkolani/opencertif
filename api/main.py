from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.db import init_db
from routers import certificates, email, history, templates, verify


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    import logging as _log
    _logger = _log.getLogger("opencertif")
    if settings.DEV_MODE:
        import warnings
        warnings.warn(
            "DEV_MODE=true : authentification DÉSACTIVÉE. NE PAS UTILISER EN PRODUCTION.",
            stacklevel=1,
        )
        _logger.warning(
            "DEV_MODE actif : toutes les requêtes sont authentifiées comme 'dev-admin' sans vérification de token."
        )
    yield


app = FastAPI(title="OpenCertif API", version="1.0.0", lifespan=lifespan)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(certificates.router, prefix="/api/certificates", tags=["certificates"])
app.include_router(verify.router, prefix="/api/verify", tags=["verify"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(templates.router, prefix="/api/templates", tags=["templates"])
app.include_router(email.router, prefix="/api/email", tags=["email"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
