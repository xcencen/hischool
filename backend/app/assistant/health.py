"""Container-local worker liveness and successful-maintenance probe (stdlib only)."""
import json
import math
import os
from pathlib import Path
import time


MARKER = Path("/tmp/campus-assistant-health.json")
HEARTBEAT_MAX_AGE = 30
MAINTENANCE_MAX_AGE = 60


class HealthWriter:
    def __init__(self, path=MARKER):
        self.path = Path(path)
        self.maintenance = None

    def __call__(self, *, mode, maintained=False, now=None):
        now = time.monotonic() if now is None else now
        if maintained:
            self.maintenance = now
        marker = {"pid": os.getpid(), "heartbeat": now,
                  "maintenance": self.maintenance, "mode": mode}
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(marker), encoding="utf-8")
        temporary.replace(self.path)


def healthy(path=MARKER, *, now=None):
    # os.kill(pid, 0) is a non-mutating process probe on the Linux runtime.
    # Windows gives kill different semantics, so never send it there.
    if os.name != "posix":
        return False
    try:
        with Path(path).open(encoding="utf-8") as source:
            raw = source.read(1025)
        if len(raw) > 1024:
            return False
        marker = json.loads(raw)
        if not isinstance(marker, dict) or set(marker) != {"pid", "heartbeat", "maintenance", "mode"}:
            return False
        if type(marker["pid"]) is not int or marker["pid"] <= 0:
            return False
        if marker["mode"] not in {"maintenance", "active"}:
            return False
        now = time.monotonic() if now is None else now
        for field, limit in (("heartbeat", HEARTBEAT_MAX_AGE), ("maintenance", MAINTENANCE_MAX_AGE)):
            value = marker[field]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= now - value <= limit:
                return False
        os.kill(marker["pid"], 0)
        return True
    except (OSError, ValueError, TypeError, OverflowError):
        return False


if __name__ == "__main__":
    status = healthy()
    print("healthy" if status else "unhealthy")
    raise SystemExit(0 if status else 1)
