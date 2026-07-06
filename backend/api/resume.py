"""Authenticated, Pro-gated resume upload and cosine match endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import MatchItem, OpportunityListItem, ResumeUploadRequest, ResumeUploadResponse
from core import models
from core.gating import can
from pipeline.resume_match import match_for_user, save_resume

router = APIRouter()

PRO_FEATURE_DETAIL = "Resume Match is a Pro feature. Upgrade to use it."


def _require_resume_match(db: Session, user: models.User) -> None:
    if not can(db, user, "resume_match"):
        raise HTTPException(status_code=403, detail=PRO_FEATURE_DETAIL)


@router.post("/resume", response_model=ResumeUploadResponse)
def upload_resume(
    request: ResumeUploadRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> ResumeUploadResponse:
    _require_resume_match(db, user)
    profile = save_resume(db, user, request.resume_text)
    version = profile.version
    db.commit()
    return ResumeUploadResponse(version=version)


@router.get("/resume/matches", response_model=list[MatchItem])
def get_resume_matches(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[MatchItem]:
    _require_resume_match(db, user)
    matches = match_for_user(db, user, limit=limit)
    return [
        MatchItem(opportunity=OpportunityListItem.from_model(opportunity), score=score)
        for opportunity, score in matches
    ]
