"""Supabase Auth verification. Delegates token validation to Supabase's own
/auth/v1/user endpoint rather than verifying the JWT locally - simpler and
safer to get right for Phase 1 than hand-rolling signature verification
against a signing scheme we have not yet confirmed (HS256 secret vs JWKS)
for this specific project. One extra network call per authenticated
request is an acceptable Phase-1 cost (Doc 02 sec 5: scale by measured
trigger - revisit with local JWT verification + caching only if this is
ever shown to matter).

A shared HTTP client reuses connections to Supabase across requests.
"""

import uuid

import httpx
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_db
from core import models
from core.config import get_settings

_supabase_http = httpx.Client(
    timeout=5.0,
    limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=30.0),
)
_DEAD_CONNECTION_ERRORS = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


def _get_supabase_user(url: str, headers: dict[str, str]) -> httpx.Response:
    try:
        return _supabase_http.get(url, headers=headers)
    except _DEAD_CONNECTION_ERRORS:
        # The server may close a pooled connection between requests; retry once on a fresh one.
        return _supabase_http.get(url, headers=headers)


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]

    settings = get_settings()
    try:
        response = _get_supabase_user(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": settings.supabase_anon_key,
            },
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
