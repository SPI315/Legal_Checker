from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.anonymization import router as anonymization_router
from app.api.routes.documents import router as documents_router
from app.core.logging import configure_logging
from app.core.settings import get_settings

configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(anonymization_router)
app.include_router(documents_router)
ui_dir = Path(__file__).parent / "ui"
app.mount("/ui", StaticFiles(directory=ui_dir), name="ui")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ui_dir / "index.html")
