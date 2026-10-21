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

import pytest

from core.config import Settings
from scripts import backup_db
from scripts.backup_db import (
    DAILY_PREFIX,
    DAILY_RETENTION_DAYS,
    SUPABASE_AUTH_DAILY_PREFIX,
    SUPABASE_AUTH_FILE_STEM,
    SUPABASE_AUTH_WEEKLY_PREFIX,
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
        objects = {
            obj["Key"]: obj
            for prefix_objects in self._objects_by_prefix.values()
            for obj in prefix_objects
            if obj["Key"].startswith(Prefix)
        }
        yield {"Contents": list(objects.values())}


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


def test_upload_auth_backup_uses_its_own_daily_and_weekly_keys() -> None:
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    designated_day = base + timedelta(days=(WEEKLY_DUMP_WEEKDAY - base.weekday()) % 7)

    client = FakeS3Client()
    result = upload_backup(
        client,
        "bucket",
        "/tmp/fake.dump",
        now=designated_day,
        daily_prefix=SUPABASE_AUTH_DAILY_PREFIX,
        weekly_prefix=SUPABASE_AUTH_WEEKLY_PREFIX,
        file_stem=SUPABASE_AUTH_FILE_STEM,
    )

    assert result.daily_key == (
        f"{SUPABASE_AUTH_DAILY_PREFIX}supabase-auth-{designated_day:%Y-%m-%d}.dump"
    )
    iso_year, iso_week, _ = designated_day.isocalendar()
    assert result.weekly_key == (
        f"{SUPABASE_AUTH_WEEKLY_PREFIX}supabase-auth-{iso_year}-W{iso_week:02d}.dump"
    )
    assert client.uploaded == [result.daily_key, result.weekly_key]

    other_day = designated_day + timedelta(days=1)
    other_result = upload_backup(
        FakeS3Client(),
        "bucket",
        "/tmp/fake.dump",
        now=other_day,
        daily_prefix=SUPABASE_AUTH_DAILY_PREFIX,
        weekly_prefix=SUPABASE_AUTH_WEEKLY_PREFIX,
        file_stem=SUPABASE_AUTH_FILE_STEM,
    )
    assert other_result.weekly_key is None


def test_pruning_app_and_auth_prefixes_is_isolated() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    old = now - timedelta(days=DAILY_RETENTION_DAYS + 1)
    objects = [
        {"Key": f"{DAILY_PREFIX}app-old.dump", "LastModified": old},
        {"Key": f"{SUPABASE_AUTH_DAILY_PREFIX}auth-old.dump", "LastModified": old},
    ]
    objects.extend(
        {"Key": f"{WEEKLY_PREFIX}app-w{i}.dump", "LastModified": now - timedelta(weeks=i)}
        for i in range(WEEKLY_RETENTION_COUNT + 1)
    )
    objects.extend(
        {
            "Key": f"{SUPABASE_AUTH_WEEKLY_PREFIX}auth-w{i}.dump",
            "LastModified": now - timedelta(weeks=i),
        }
        for i in range(WEEKLY_RETENTION_COUNT + 1)
    )

    app_client = FakeS3Client({"bucket": list(objects)})
    _prune(
        app_client,
        "bucket",
        DAILY_PREFIX,
        keep_newest=None,
        max_age_days=DAILY_RETENTION_DAYS,
        now=now,
    )
    _prune(
        app_client,
        "bucket",
        WEEKLY_PREFIX,
        keep_newest=WEEKLY_RETENTION_COUNT,
        max_age_days=None,
        now=now,
    )
    assert f"{DAILY_PREFIX}app-old.dump" in app_client.deleted
    assert all(not key.startswith("supabase-auth/") for key in app_client.deleted)

    auth_client = FakeS3Client({"bucket": list(objects)})
    _prune(
        auth_client,
        "bucket",
        SUPABASE_AUTH_DAILY_PREFIX,
        keep_newest=None,
        max_age_days=DAILY_RETENTION_DAYS,
        now=now,
    )
    _prune(
        auth_client,
        "bucket",
        SUPABASE_AUTH_WEEKLY_PREFIX,
        keep_newest=WEEKLY_RETENTION_COUNT,
        max_age_days=None,
        now=now,
    )
    assert f"{SUPABASE_AUTH_DAILY_PREFIX}auth-old.dump" in auth_client.deleted
    assert all(key.startswith("supabase-auth/") for key in auth_client.deleted)


def test_auth_mode_without_supabase_db_url_exits_before_dump(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        supabase_db_url="",
        backup_s3_endpoint_url="https://example.invalid",
        backup_s3_access_key_id="access-key",
        backup_s3_secret_access_key="secret-key",
        backup_s3_bucket="bucket",
    )
    dump_called = False

    def fake_dump(database_url: str, output_path: str) -> None:
        nonlocal dump_called
        dump_called = True

    monkeypatch.setattr(backup_db, "get_settings", lambda: settings)
    monkeypatch.setattr(backup_db, "dump_supabase_auth", fake_dump)

    with pytest.raises(SystemExit) as exc_info:
        backup_db.main(["--supabase-auth"])

    assert exc_info.value.code == 1
    assert dump_called is False


def test_auth_dump_uses_schema_flags_and_libpq_url(monkeypatch) -> None:
    captured_args = []

    def fake_run(args, **kwargs):
        captured_args.extend(args)
        return backup_db.subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(backup_db.subprocess, "run", fake_run)

    backup_db.dump_supabase_auth(
        "postgresql+psycopg://user:password@example.invalid:5432/postgres",
        "/tmp/auth.dump",
    )

    assert "--schema=auth" in captured_args
    assert "--format=custom" in captured_args
    assert captured_args[-1] == "postgresql://user:password@example.invalid:5432/postgres"
    assert "+psycopg" not in captured_args[-1]


def test_pg_dump_failures_redact_connection_urls(monkeypatch) -> None:
    sqlalchemy_url = "postgresql+psycopg://user:s3cretpw@host:5432/postgres"
    libpq_url = "postgresql://user:s3cretpw@host:5432/postgres"

    def fake_run(args, **kwargs):
        return backup_db.subprocess.CompletedProcess(
            args,
            23,
            stdout="",
            stderr=f"failed with {sqlalchemy_url} and {libpq_url}",
        )

    monkeypatch.setattr(backup_db.subprocess, "run", fake_run)

    for dump_function in (backup_db.dump_supabase_auth, backup_db.dump_database):
        with pytest.raises(RuntimeError) as exc_info:
            dump_function(sqlalchemy_url, "/tmp/backup.dump")

        message = str(exc_info.value)
        assert sqlalchemy_url not in message
        assert libpq_url not in message
        assert "s3cretpw" not in message
        assert "exit 23" in message
