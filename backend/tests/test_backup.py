"""Unit tests for the backup retention math (Doc 03 sec 8/9: "keep 7 daily
+ 4 weekly"). The dump/upload/restore mechanics themselves were verified
in a live drill (Docker: real Alembic-migrated schema -> pg_dump -> MinIO
-> pg_restore -> row-for-row diff against the source, documented in the
Part 2.2 write-up) rather than re-proven here - that drill needs real
time/network/processes a unit test can't reproduce. What a unit test CAN
cover cheaply and deterministically is the retention logic, which depends
on S3 object ages/counts that would otherwise require waiting real days to
exercise.
"""

from datetime import datetime, timedelta, timezone

from scripts.backup_db import (
    DAILY_PREFIX,
    DAILY_RETENTION_DAYS,
    WEEKLY_DUMP_WEEKDAY,
    WEEKLY_PREFIX,
    WEEKLY_RETENTION_COUNT,
    _prune,
    to_libpq_url,
    upload_backup,
)


class FakePaginator:
    def __init__(self, objects_by_prefix: dict[str, list[dict]]) -> None:
        self._objects_by_prefix = objects_by_prefix

    def paginate(self, Bucket, Prefix):
        yield {"Contents": list(self._objects_by_prefix.get(Prefix, []))}


class FakeS3Client:
    """Minimal double covering exactly what backup_db.py calls:
    upload_file, get_paginator("list_objects_v2"), delete_object."""

    def __init__(self, objects_by_prefix: dict[str, list[dict]] | None = None) -> None:
        self._objects_by_prefix = objects_by_prefix or {}
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    def upload_file(self, local_path, bucket, key) -> None:
        self.uploaded.append(key)

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self._objects_by_prefix)

    def delete_object(self, Bucket, Key) -> None:
        self.deleted.append(Key)
        for objs in self._objects_by_prefix.values():
            objs[:] = [o for o in objs if o["Key"] != Key]


def test_to_libpq_url_strips_sqlalchemy_driver_suffix() -> None:
    assert to_libpq_url("postgresql+psycopg://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"


def test_prune_daily_deletes_objects_older_than_retention_window() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    objects = {
        DAILY_PREFIX: [
            {"Key": f"{DAILY_PREFIX}recent.dump", "LastModified": now - timedelta(days=1)},
            {
                "Key": f"{DAILY_PREFIX}old.dump",
                "LastModified": now - timedelta(days=DAILY_RETENTION_DAYS + 1),
            },
        ]
    }
    client = FakeS3Client(objects)

    deleted = _prune(
        client, "bucket", DAILY_PREFIX, keep_newest=None, max_age_days=DAILY_RETENTION_DAYS, now=now
    )

    assert deleted == [f"{DAILY_PREFIX}old.dump"]


def test_prune_weekly_keeps_only_newest_n() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    objects = {
        WEEKLY_PREFIX: [
            {"Key": f"{WEEKLY_PREFIX}w{i}.dump", "LastModified": now - timedelta(weeks=i)}
            for i in range(WEEKLY_RETENTION_COUNT + 2)
        ]
    }
    client = FakeS3Client(objects)

    deleted = _prune(
        client,
        "bucket",
        WEEKLY_PREFIX,
        keep_newest=WEEKLY_RETENTION_COUNT,
        max_age_days=None,
        now=now,
    )

    assert set(deleted) == {
        f"{WEEKLY_PREFIX}w{i}.dump"
        for i in range(WEEKLY_RETENTION_COUNT, WEEKLY_RETENTION_COUNT + 2)
    }


def test_upload_backup_creates_weekly_key_only_on_the_designated_weekday() -> None:
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    days_until_designated = (WEEKLY_DUMP_WEEKDAY - base.weekday()) % 7
    designated_day = base + timedelta(days=days_until_designated)
    assert designated_day.weekday() == WEEKLY_DUMP_WEEKDAY

    on_designated_day = upload_backup(
        FakeS3Client(), "bucket", "/tmp/fake.dump", now=designated_day
    )
    assert on_designated_day.weekly_key is not None

    other_day = designated_day + timedelta(days=1)
    on_other_day = upload_backup(FakeS3Client(), "bucket", "/tmp/fake.dump", now=other_day)
    assert on_other_day.weekly_key is None


def test_upload_backup_always_creates_a_daily_key() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    client = FakeS3Client()

    result = upload_backup(client, "bucket", "/tmp/fake.dump", now=now)

    assert result.daily_key == f"{DAILY_PREFIX}aspirova-2026-07-10.dump"
    assert result.daily_key in client.uploaded
