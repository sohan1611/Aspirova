"""Supabase Auth verification. Delegates token validation to Supabase's own
/auth/v1/user endpoint rather than verifying the JWT locally - simpler and
safer to get right for Phase 1 than hand-rolling signature verification
against a signing scheme we have not yet confirmed (HS256 secret vs JWKS)
for this specific project. One extra network call per authenticated
request is an acceptable Phase-1 cost (Doc 02 sec 5: scale by measured
trigger - revisit with local JWT verification + caching only if this is
ever shown to matter).

BLOCKED ON CREDENTIALS: untested against a real token - SUPABASE_URL and
SUPABASE_ANON_KEY are still blank in .env as of this writing.
"""

import uuid

import httpx
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db
from core import models
from core.config import get_settings


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]

    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_anon_key,
            },
            timeout=5.0,
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    auth_user = response.json()
    user_id = uuid.UUID(auth_user["id"])

    user = db.get(models.User, user_id)
    if user is None:
        # First authenticated request from this Supabase Auth user - mirror
        # them into our users table (Doc 03 sec 4.1: users.id matches
        # auth.users.id).
        user = models.User(id=user_id, email=auth_user.get("email"))
        db.add(user)
        db.commit()

    return user
