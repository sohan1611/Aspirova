from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import (
    account,
    bookmarks,
    company,
    copilot,
    dream_companies,
    feed,
    for_you,
    opportunity,
    payments,
    plans,
    referral,
    resume,
    search,
    sitemap,
    stats,
    waitlist,
)
from api.middleware import RateLimitMiddleware, ReadCacheMiddleware, TimingMiddleware
from core.config import get_settings

settings = get_settings()

app = FastAPI(title="Aspirova API", version="0.1.0")

# Order matters: Starlette makes the LAST-added middleware the outermost
# one. ReadCache and RateLimit are added first (innermost -> middle), then
# Timing (wraps both, so every response gets X-Total-Time-Ms/X-DB-Time-Ms,
# including a 429 or a cache hit), then CORSMiddleware last so it wraps
# everything - a 429 or a cached response must still pass through CORS on
# the way out (Doc handoffs/PHASE-2-HANDOFF.md sec 11.5), or the browser
# hides it as a CORS failure.
app.add_middleware(ReadCacheMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(feed.router)
app.include_router(for_you.router)
app.include_router(account.router)
app.include_router(search.router)
app.include_router(opportunity.router)
app.include_router(company.router)
app.include_router(bookmarks.router)
app.include_router(copilot.router)
app.include_router(dream_companies.router)
app.include_router(resume.router)
app.include_router(payments.router)
app.include_router(plans.router)
app.include_router(referral.router)
app.include_router(sitemap.router)
app.include_router(stats.router)
app.include_router(waitlist.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}
