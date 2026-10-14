"""Dump PostgreSQL to a binary archive or restore into a NEW database."""

import argparse
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from deployment_support import Compose


def backup(compose: Compose, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing an existing backup. A binary stream
    # avoids PowerShell's text encoding conversions of a custom-format dump.
    with destination.open("xb") as archive:
        destination.chmod(0o600)
        try:
            subprocess.run(
                [
                    *compose.command,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "-U",
                    "seismic_admin",
                    "-d",
                    "seismic",
                    "--format=custom",
                    "--no-owner",
                ],
                stdout=archive,
                check=True,
                timeout=180,
            )
        except BaseException:
            archive.close()
            destination.unlink()
            raise


def restore(compose: Compose, archive: Path, database: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database) or database in {
        "seismic",
        "postgres",
        "template0",
        "template1",
    }:
        raise ValueError("Use a new database name, such as seismic_restore_check")
    with archive.open("rb") as source:
        # createdb fails if the target exists. This tool never drops databases.
        compose.run(
            "exec", "-T", "postgres", "createdb", "-U", "seismic_admin", database
        )
        subprocess.run(
            [
                *compose.command,
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                "seismic_admin",
                "--dbname",
                database,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
            ],
            stdin=source,
            check=True,
            timeout=180,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--project", required=True)
    sub = parser.add_subparsers(dest="operation", required=True)
    dump = sub.add_parser("backup")
    dump.add_argument("archive", type=Path, nargs="?")
    dump.add_argument("--directory", type=Path, default=Path("backups"))
    load = sub.add_parser("restore")
    load.add_argument("archive", type=Path)
    load.add_argument("--database", required=True)
    args = parser.parse_args()
    compose = Compose(args.env_file, args.project)
    if args.operation == "backup":
        archive = args.archive or args.directory / (
            f"seismic-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.dump"
        )
        backup(compose, archive)
        print(f"Backup saved to {archive}")
    else:
        restore(compose, args.archive, args.database)
        print(
            f"Restored into new database {args.database}; inspect before switching services"
        )


if __name__ == "__main__":
    main()
