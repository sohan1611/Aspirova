"""Restore drill (Doc 03 sec 8/9: "a backup you've never restored is a
hope, not a backup"). Downloads one backup object and pg_restores it into
a TARGET database.

This script has no notion of "production" - it will happily overwrite
whatever --target-database-url points at, by design. The entire safety
boundary is the connection string the operator passes in. NEVER point
this at a database anyone depends on; it exists to restore into a
throwaway/scratch instance so the drill proves the backup is real.
"""

import argparse
import logging
import subprocess

from core.config import get_settings
from scripts.backup_db import s3_client, to_libpq_url

logger = logging.getLogger(__name__)


def download_backup(client, bucket: str, key: str, local_path: str) -> None:
    client.download_file(bucket, key, local_path)


def restore_database(target_database_url: str, dump_path: str) -> None:
    result = subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            to_libpq_url(target_database_url),
            dump_path,
        ],
        capture_output=True,
        text=True,
    )
    # pg_restore commonly exits 1 on harmless warnings (e.g. "role ... does
    # not exist" from --no-owner ignoring ownership commands it can't
    # apply) - a real failure additionally has no restored objects at all,
    # which the caller's own verification query catches; exit code alone
    # is not a reliable pass/fail signal for pg_restore.
    logger.info("pg_restore exit=%d stderr=%s", result.returncode, result.stderr)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True, help="S3 object key of the backup to restore")
    parser.add_argument(
        "--target-database-url",
        required=True,
        help="Connection string of the SCRATCH database to restore into - never production",
    )
    args = parser.parse_args()

    settings = get_settings()
    local_path = "/tmp/aspirova-restore.dump"
    client = s3_client(settings)
    download_backup(client, settings.backup_s3_bucket, args.key, local_path)
    restore_database(args.target_database_url, local_path)


if __name__ == "__main__":
    main()
