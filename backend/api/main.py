from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import bookmarks, feed, opportunity, search
from api.middleware import RateLimitMiddleware, ReadCacheMiddleware
from core.config import get_settings

settings = get_settings()

app = FastAPI(title="Aspirova API", version="0.1.0")

# Order matters: Starlette makes the LAST-added middleware the outermost
# one. ReadCache and RateLimit are added first (innermost -> middle) so
# CORSMiddleware, added last, wraps both - a 429 or a cached response must
# still pass through CORS on the way out (Doc handoffs/PHASE-2-HANDOFF.md
# sec 11.5), or the browser hides it as a CORS failure.
app.add_middleware(ReadCacheMiddleware)
app.add_middleware(RateLimitMiddleware)
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
