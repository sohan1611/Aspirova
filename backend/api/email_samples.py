"""Public, database-free examples of the emails described on the pricing page."""

from fastapi import APIRouter, HTTPException, Response

from core.email_samples import render_sample

router = APIRouter()


@router.get("/email-samples/{kind}")
def email_sample(kind: str, response: Response) -> dict[str, str]:
    sample = render_sample(kind)
    if sample is None:
        raise HTTPException(status_code=404, detail="Email sample not found")
    subject, html = sample
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {"subject": subject, "html": html}
