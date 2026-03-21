from fastapi import FastAPI

from app.api.routes.anonymization import router as anonymization_router
from app.core.settings import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(anonymization_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
