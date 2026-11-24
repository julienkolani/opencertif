import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# api/main.py is run in production as `uvicorn main:app` with WORKDIR=/app
# containing main.py, core/ and routers/ directly (see api/Dockerfile). Its
# internal imports are therefore unprefixed ("from core.x import y"), so
# tests must resolve modules the same way: put api/ on sys.path as the
# effective root, not the repo root.
sys.path.insert(0, str(ROOT / "api"))
