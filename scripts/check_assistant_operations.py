"""Read existing Compose health and DB aggregates. Never start or change services."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def health_status(rows, services):
    result, code = [], 0
    for service in services:
        matches = [row for row in rows if row.get("Service") == service]
        if not matches:
            result.append({"service": service, "state": "missing", "health": "unknown"})
            code = max(code, 1)
        for row in matches:
            state = row.get("State")
            health = row.get("Health")
            state = state if state in {"running", "exited", "created", "restarting", "paused", "dead", "removing"} else "unknown"
            health = health if health in {"healthy", "unhealthy", "starting"} else "unknown"
            result.append({"service": service, "state": state, "health": health})
            if state != "running" or health in {"unhealthy", "starting"}:
                code = max(code, 1)
            elif health == "unknown":
                code = 2
    return code, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--project", required=True)
    parser.add_argument("--compose-file", action="append", required=True, type=Path)
    parser.add_argument("--service", action="append", required=True,
                        help="Each required running service, including API, worker and MCP")
    parser.add_argument("--api-service", default="api")
    args = parser.parse_args(argv)
    command = [args.docker, "compose", "-p", args.project]
    for path in args.compose_file:
        command.extend(["-f", str(path)])
    deadline = time.monotonic()+10

    def run(extra):
        return subprocess.run(command+extra, capture_output=True, text=True, encoding='utf-8',
                              timeout=max(.001, deadline-time.monotonic()))

    try:
        checked = run(["ps", "--all", "--format", "json"])
        if checked.returncode:
            raise ValueError("unavailable")
        raw = checked.stdout.strip()
        rows = json.loads(raw) if raw.startswith("[") else [json.loads(line) for line in raw.splitlines()]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid health response")
        health_code, services = health_status(rows, args.service)
        checked = run(["exec", "-T", args.api_service, "python", "-B", "-m", "app.assistant.operations"])
        data = json.loads(checked.stdout)
        if not isinstance(data, dict) or checked.returncode not in (0, 1) or data.get("status") not in ("ok", "warning"):
            raise ValueError("unavailable")
        code = max(health_code, checked.returncode)
        result = {"status": ("ok", "warning", "unavailable")[code], "services": services, "operations": data}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        code, result = 2, {"status": "unavailable"}
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
