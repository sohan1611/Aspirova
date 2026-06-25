from fastapi import FastAPI

from core.config import get_settings

app = FastAPI(title="Aspirova API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "env": settings.env}
