"""Nightly independent backup: pg_dump the production DB to S3-compatible
object storage, with retention (Doc 03 sec 8/9: "keep 7 daily + 4
weekly"). Runs from GitHub Actions cron, never the Render dyno - same
"crawler never runs on the web process" principle (Doc 02 sec 3.3),
extended to this operational job.

Independent of Supabase's own backup feature on purpose. That feature
needs Supabase Pro, which Doc 06's cost model gates behind a measured
usage trigger (free tier lasts to ~1k users) - same scale-by-measured-
trigger rule as everything else (Doc 02 sec 5), not something to switch on
just to satisfy this part. This script is the primary safety net
regardless of that decision (Doc 03 sec 8: "never rely solely on the
provider").

pg_dump's custom format (-Fc) is used, not plain SQL + gzip: it is already
compressed and is the format pg_restore expects directly - one file, one
round trip either way, and it supports selective/parallel restore later if
ever needed.

Works unchanged against either Cloudflare R2 or Backblaze B2 - both expose
an S3-compatible API, so only the endpoint URL (core/config.py) differs.
"""

import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import boto3

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

DAILY_PREFIX = "daily/"
WEEKLY_PREFIX = "weekly/"
DAILY_RETENTION_DAYS = 7
WEEKLY_RETENTION_COUNT = 4
# Arbitrary but fixed choice of "which daily dump also becomes this week's
# weekly dump" - datetime.weekday(): Monday=0 ... Sunday=6.
WEEKLY_DUMP_WEEKDAY = 6


def to_libpq_url(database_url: str) -> str:
    """pg_dump/pg_restore parse connection strings via libpq, which does
    not understand SQLAlchemy's driver-qualified scheme
    (postgresql+psycopg://, as used everywhere else in this codebase -
    core/db.py) - strip it to the plain postgresql:// scheme libpq
    expects."""
    parts = urlsplit(database_url)
    scheme = parts.scheme.split("+", 1)[0]
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def dump_database(database_url: str, output_path: str) -> None:
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--file", output_path, to_libpq_url(database_url)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed (exit {result.returncode}): {result.stderr}")


def s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.backup_s3_endpoint_url,
        aws_access_key_id=settings.backup_s3_access_key_id,
        aws_secret_access_key=settings.backup_s3_secret_access_key,
    )


@dataclass
class BackupResult:
    daily_key: str
    weekly_key: str | None
    pruned_daily: list[str]
    pruned_weekly: list[str]


def upload_backup(client, bucket: str, local_path: str, *, now: datetime) -> BackupResult:
    daily_key = f"{DAILY_PREFIX}aspirova-{now:%Y-%m-%d}.dump"
    client.upload_file(local_path, bucket, daily_key)
    logger.info("uploaded %s", daily_key)

    weekly_key = None
    if now.weekday() == WEEKLY_DUMP_WEEKDAY:
        iso_year, iso_week, _ = now.isocalendar()
        weekly_key = f"{WEEKLY_PREFIX}aspirova-{iso_year}-W{iso_week:02d}.dump"
        client.upload_file(local_path, bucket, weekly_key)
        logger.info("uploaded %s", weekly_key)

    pruned_daily = _prune(
        client, bucket, DAILY_PREFIX, keep_newest=None, max_age_days=DAILY_RETENTION_DAYS, now=now
    )
    pruned_weekly = _prune(
        client,
        bucket,
        WEEKLY_PREFIX,
        keep_newest=WEEKLY_RETENTION_COUNT,
        max_age_days=None,
        now=now,
    )

    return BackupResult(daily_key, weekly_key, pruned_daily, pruned_weekly)


def _prune(
    client,
    bucket: str,
    prefix: str,
    *,
    keep_newest: int | None,
    max_age_days: int | None,
    now: datetime,
) -> list[str]:
    """Delete objects under `prefix` beyond the retention rule. Exactly one
    of keep_newest (count-based, for weekly) / max_age_days (age-based, for
    daily) is set - deletion is driven by S3's own LastModified metadata,
    not by parsing dates out of key names, so it can't be thrown off by a
    renamed key or a month/year rollover in the filename."""
    paginator = client.get_paginator("list_objects_v2")
    objects = [
        obj
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
    ]
    objects.sort(key=lambda o: o["LastModified"], reverse=True)

    if keep_newest is not None:
        to_delete = objects[keep_newest:]
    else:
        cutoff = now - timedelta(days=max_age_days)
        to_delete = [o for o in objects if o["LastModified"] < cutoff]

    deleted = []
    for obj in to_delete:
        client.delete_object(Bucket=bucket, Key=obj["Key"])
        deleted.append(obj["Key"])
        logger.info("pruned %s", obj["Key"])

    return deleted


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()

    if not (
        settings.backup_s3_endpoint_url
        and settings.backup_s3_access_key_id
        and settings.backup_s3_secret_access_key
        and settings.backup_s3_bucket
    ):
        logger.error("BACKUP_S3_* is not fully configured - see backend/.env.example. Aborting.")
        sys.exit(1)

    local_path = "/tmp/aspirova-backup.dump"
    dump_database(settings.database_url, local_path)

    client = s3_client(settings)
    result = upload_backup(
        client, settings.backup_s3_bucket, local_path, now=datetime.now(timezone.utc)
    )
    logger.info(
        "backup complete: daily=%s weekly=%s pruned_daily=%d pruned_weekly=%d",
        result.daily_key,
        result.weekly_key,
        len(result.pruned_daily),
        len(result.pruned_weekly),
    )


if __name__ == "__main__":
    main()
