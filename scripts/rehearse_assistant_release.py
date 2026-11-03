"""Fixed disposable project only. Binary backups and reports stay on F drive."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_assistant import validate_test_project

PROJECT = "my-campus-ai-m5-release"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default="F:/my-campus-dev/docker/app/resources/bin/docker.exe")
    parser.add_argument("--output", type=Path, default=Path("F:/my-campus-dev/temp/m5-release/rehearsal"))
    parser.add_argument("--project", default="my-campus-ai-m6-release", type=validate_test_project)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--test-image", default="my-campus-ai-m2-test-tests:latest")
    parser.add_argument("--old-image", default="my-campus-backend:m4-verified")
    args = parser.parse_args()
    global PROJECT
    PROJECT = args.project
    root = args.source.resolve()
    output = args.output.resolve()
    if output.drive.upper() != "F:" or output.exists():
        raise SystemExit("A new F-drive artifact directory is required")
    output.mkdir(parents=True)
    overlay = output / "compose.json"
    overlay.write_text(json.dumps({"services": {"tests": {
        "image": args.test_image,
        "environment": {"M5_RELEASE_PROJECT": PROJECT},
        "volumes": [f"{(root/'backend'/name).as_posix()}:/app/{name}:ro" for name in ("app", "tests", "migrations")]
    }}}), encoding="utf-8")
    command = [args.docker, "compose", "-p", PROJECT, "-f", str(root/"compose.assistant-test.yaml"), "-f", str(overlay)]
    def run(extra, data=None):
        result = subprocess.run(command + extra, cwd=root, input=data, capture_output=True, timeout=180)
        if result.returncode:
            # SQL/driver stdout may contain private values: keep only safe stage.
            raise RuntimeError("Isolated release operation failed: " + extra[0])
        return result.stdout
    def phase(name):
        data = run(["run", "--rm", "--no-deps", "tests", "python", "-B", "tests/support/assistant_release.py", name])
        result = json.loads(data)
        (output/(name+".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("passed phase=" + name, flush=True)
        return result
    report = {"project": PROJECT, "passed": False, "test_image": args.test_image, "old_image": args.old_image}
    for key, image in (("test_image_id", args.test_image), ("old_image_id", args.old_image)):
        inspected = subprocess.run([args.docker, "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, timeout=15)
        if inspected.returncode: raise RuntimeError("Required local image missing")
        report[key] = inspected.stdout.decode().strip()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, timeout=15)
    report["commit"] = commit.stdout.decode().strip() if commit.returncode == 0 else "snapshot-see-manifest"
    started = False
    probe_attempted = False
    probe_name = PROJECT + "-old-image-probe"
    try:
        if run(["ps", "-a", "-q"]).strip():
            raise ValueError("Refuse pre-existing rehearsal containers")
        started = True
        run(["up", "-d", "--wait", "test-mysql", "checkpoint-mysql", "test-redis"])
        report["prepare"] = phase("prepare")
        dump = run(["exec", "-T", "test-mysql", "sh", "-c",
            'test "$MYSQL_DATABASE" = my_campus_test && MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump '
            '--user="$MYSQL_USER" --single-transaction --no-tablespaces --set-gtid-purged=OFF '
            '--column-statistics=0 --default-character-set=utf8mb4 --hex-blob my_campus_test'])
        assert b"CREATE TABLE `users`" in dump and b"CREATE TABLE `alembic_version`" in dump
        assert b"CREATE DATABASE" not in dump and b"DROP DATABASE" not in dump
        backup = output/"synthetic-0005.sql"
        backup.write_bytes(dump)
        report["backup_sha256"] = hashlib.sha256(dump).hexdigest()
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == report["backup_sha256"]
        run(["exec", "-T", "checkpoint-mysql", "sh", "-c",
            'test "$MYSQL_DATABASE" = my_campus_test && MYSQL_PWD="$MYSQL_PASSWORD" exec mysql '
            '--user="$MYSQL_USER" --default-character-set=utf8mb4 my_campus_test'], data=dump)
        report["restored"] = phase("restored")
        report["upgrade"] = phase("upgrade")
        report["rollback"] = phase("rollback")
        existing = subprocess.run([args.docker, "container", "inspect", probe_name], capture_output=True, timeout=15)
        if existing.returncode == 0:
            raise ValueError("Refuse pre-existing image probe")
        probe_attempted = True
        old = subprocess.run([args.docker, "run", "--name", probe_name,
            "--label", "campus.release.project="+PROJECT, "--rm", "--pull", "never", "--network", PROJECT+"_default",
            "--read-only", "--tmpfs", "/tmp",
            "-e", "CAMPUS_DATABASE_URL=mysql+asyncmy://my_campus:m1-isolated-test-only@test-mysql:3306/my_campus_test?charset=utf8mb4",
            "-e", "CAMPUS_REDIS_URL=redis://test-redis:6379/15",
            "-e", "CAMPUS_JWT_SECRET=m1-isolated-integration-tests-only-signing-key-2026",
            "-e", "CAMPUS_ASSISTANT_ENABLED=false", "-e", "CAMPUS_ASSISTANT_ALLOW_CAMPUS_DATA=false",
            "-v", str(root/"backend/tests/support/assistant_rollback_probe.py")+":/verify.py:ro",
            args.old_image, "python", "-B", "/verify.py"], capture_output=True, timeout=60)
        assert old.returncode == 0, "Previous verified image rollback check failed"
        report["old_image_rollback"] = json.loads(old.stdout)
        print("passed phase=old_image_rollback", flush=True)
        report["passed"] = True
    finally:
        cleanup_failure = None
        try:
            if probe_attempted:
                state = subprocess.run([args.docker, "container", "inspect", "--format",
                    '{{ index .Config.Labels "campus.release.project" }}', probe_name], capture_output=True, timeout=15)
                if state.returncode == 0:
                    if state.stdout.decode().strip() != PROJECT:
                        raise ValueError("Refuse unrelated probe cleanup")
                    subprocess.run([args.docker, "rm", "-f", probe_name], check=True, capture_output=True, timeout=30)
            if started:
                # Only the fixed project created by this invocation is removed.
                run(["down"])
        except Exception as error:
            cleanup_failure = type(error).__name__
            report["passed"] = False
            report["cleanup_failure"] = cleanup_failure
        finally:
            (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if cleanup_failure:
            raise RuntimeError("Isolated cleanup failed; inspect the saved report")
    print(json.dumps({"passed": report["passed"], "report": str(output/"report.json"), "backup_sha256": report["backup_sha256"]}))


if __name__ == "__main__":
    main()
