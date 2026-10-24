"""Back up only the isolated my-campus demo schema to the agreed F drive."""

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--output-dir", type=Path, default=Path("F:/my-campus-dev/backups"))
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = options.output_dir.resolve()
    if output.drive.upper() != "F:":
        raise SystemExit("Local database backups must be stored on the agreed F: drive")
    command = [options.docker, "compose", "--env-file", str(root/".env.compose"),
               "-f", str(root/"compose.yaml"), "--project-name", "my-campus",
               "exec", "-T", "mysql", "sh", "-c",
               'test "$MYSQL_DATABASE" = my_campus && MYSQL_PWD="$MYSQL_PASSWORD" '
               'exec mysqldump --user="$MYSQL_USER" --single-transaction --no-tablespaces '
               '--set-gtid-purged=OFF --column-statistics=0 --default-character-set=utf8mb4 '
               '--hex-blob my_campus']
    result = subprocess.run(command, cwd=root, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise SystemExit("Database backup failed; no schema migration should be run")
    tables = re.findall(rb"CREATE TABLE `([^`]+)`", result.stdout)
    if b"users" not in tables or b"alembic_version" not in tables:
        raise SystemExit("Backup verification failed: expected campus tables are missing")
    if b"CREATE DATABASE" in result.stdout or b"DROP DATABASE" in result.stdout:
        raise SystemExit("Backup verification failed: unexpected database-level SQL")
    output.mkdir(parents=True, exist_ok=True)
    label = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    path = output/f"my_campus-{label}.sql"
    with path.open("xb") as saved:
        saved.write(result.stdout)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != hashlib.sha256(result.stdout).hexdigest():
        raise SystemExit("Backup checksum verification failed")
    manifest = {"database": "my_campus", "path": str(path), "sha256": digest,
                "bytes": len(result.stdout), "tables": [table.decode() for table in tables]}
    path.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
