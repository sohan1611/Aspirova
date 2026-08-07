"""Fail-open notification of changed opportunity pages to the frontend."""

import logging
import os
from collections.abc import Iterable

import httpx

logger = logging.getLogger(__name__)

REVALIDATION_BATCH_SIZE = 500
MAX_CHANGED_SLUGS = 5_000
REQUEST_TIMEOUT_SECONDS = 10.0


def notify_changed(slugs: Iterable[str]) -> dict[str, int | str]:
    """Notify the frontend of changed slugs without ever failing a crawl."""
    result: dict[str, int | str] = {
        "status": "unconfigured",
        "changed": 0,
        "notified": 0,
        "batches": 0,
        "failed_batches": 0,
    }

    try:
        url = os.getenv("REVALIDATE_URL", "").strip()
        secret = os.getenv("REVALIDATE_SECRET", "").strip()
    except Exception as exc:
        logger.warning(
            "Could not read revalidation configuration; notification skipped (error=%s)",
            type(exc).__name__,
        )
        result["status"] = "configuration_error"
        return result

    if not url or not secret:
        return result

    unique_slugs: list[str] = []
    seen: set[str] = set()
    try:
        for slug in slugs:
            if slug in seen:
                continue
            seen.add(slug)
            unique_slugs.append(slug)
            if len(unique_slugs) > MAX_CHANGED_SLUGS:
                logger.warning(
                    "Revalidation notification skipped: changed slug count exceeds limit=%d",
                    MAX_CHANGED_SLUGS,
                )
                result["status"] = "skipped_limit"
                result["changed"] = len(unique_slugs)
                return result
    except Exception as exc:
        logger.warning(
            "Could not collect changed slugs; revalidation notification skipped (error=%s)",
            type(exc).__name__,
        )
        result["status"] = "collection_error"
        return result

    result["changed"] = len(unique_slugs)
    if not unique_slugs:
        result["status"] = "empty"
        return result

    for offset in range(0, len(unique_slugs), REVALIDATION_BATCH_SIZE):
        batch = unique_slugs[offset : offset + REVALIDATION_BATCH_SIZE]
        result["batches"] += 1
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {secret}"},
                json={"slugs": batch},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            result["notified"] += len(batch)
        except Exception as exc:
            result["failed_batches"] += 1
            logger.warning(
                "Revalidation notification batch failed (size=%d, error=%s)",
                len(batch),
                type(exc).__name__,
            )

    if result["failed_batches"] == 0:
        result["status"] = "ok"
    elif result["notified"] == 0:
        result["status"] = "failed"
    else:
        result["status"] = "partial"
    return result
