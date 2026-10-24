"""Restore a verified dump only into the isolated my-campus-test database."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    options = parser.parse_args()
    backup = options.backup.resolve(strict=True)
    manifest = json.loads(backup.with_suffix(".json").read_text(encoding="utf-8"))
    data = backup.read_bytes()
    if manifest["database"] != "my_campus" or hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise SystemExit("Backup identity or checksum did not match")
    if re.search(rb"(?mi)^\s*(CREATE DATABASE|DROP DATABASE|USE\s)", data):
        raise SystemExit("Refusing a dump containing database-selection commands")
    root = Path(__file__).resolve().parents[1]

    def sql(database: str, service: str, file: str, project: str, content: bytes) -> bytes:
        script = f'test "$MYSQL_DATABASE" = {database} && MYSQL_PWD="$MYSQL_PASSWORD" exec mysql --user="$MYSQL_USER" --batch --skip-column-names --default-character-set=utf8mb4 {database}'
        result = subprocess.run([options.docker, "compose", "--env-file", str(root/".env.compose"),
            "-f", str(root/file), "--project-name", project, "exec", "-T", service, "sh", "-c", script],
            cwd=root, input=content, capture_output=True, timeout=120, check=False)
        if result.returncode:
            raise SystemExit("Backup recovery check failed; inspect the isolated test service")
        return result.stdout

    before = sql("my_campus_test", "test-mysql", "compose.test.yaml", "my-campus-test", b"SHOW TABLES;")
    existing = set(before.decode().split())
    if existing - set(manifest["tables"]):
        raise SystemExit("Test database has tables outside this backup; refusing to overwrite")
    # The source schema is only read. Restoration cannot select the source DB.
    primary = sql("my_campus", "mysql", "compose.yaml", "my-campus", b"SELECT COUNT(*) FROM users; CHECKSUM TABLE users;")
    sql("my_campus_test", "test-mysql", "compose.test.yaml", "my-campus-test", data)
    restored = sql("my_campus_test", "test-mysql", "compose.test.yaml", "my-campus-test", b"SELECT COUNT(*) FROM users; CHECKSUM TABLE users;")
    primary_values = [line.split()[-1] for line in primary.splitlines() if line.strip()]
    restored_values = [line.split()[-1] for line in restored.splitlines() if line.strip()]
    if primary_values != restored_values:
        raise SystemExit("Restored row count or checksum does not match the source snapshot")
    print("PASS: isolated backup restore matched user count and MySQL table checksum.")


if __name__ == "__main__":
    main()
