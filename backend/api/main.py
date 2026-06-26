from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import bookmarks, feed, opportunity, search
from core.config import get_settings

settings = get_settings()

app = FastAPI(title="Aspirova API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(feed.router)
app.include_router(search.router)
app.include_router(opportunity.router)
app.include_router(bookmarks.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}
