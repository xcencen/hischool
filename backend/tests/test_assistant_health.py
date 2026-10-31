"""Local health contract: freshness must include successful maintenance."""
import json
import os
import subprocess
import sys

import pytest

from app.assistant import health

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Worker health targets Linux containers")


def test_fresh_worker_is_healthy_and_failed_maintenance_cannot_refresh_it(tmp_path):
    path = tmp_path / "health.json"
    writer = health.HealthWriter(path)
    writer(mode="maintenance", now=99)
    assert not health.healthy(path, now=99)
    writer(mode="maintenance", maintained=True, now=100)
    assert health.healthy(path, now=101)
    writer(mode="active", now=155)
    assert health.healthy(path, now=155)
    writer(mode="active", now=161)
    assert not health.healthy(path, now=161)


@pytest.mark.parametrize("changes", [
    {"heartbeat": 60}, {"maintenance": 30}, {"heartbeat": 101},
    {"maintenance": 101}, {"pid": 0}, {"pid": True},
    {"heartbeat": float("nan")}, {"heartbeat": True}, {"maintenance": None},
    {"mode": "secret"}, {"extra": "private"},
])
def test_invalid_marker_is_unhealthy(tmp_path, changes):
    path = tmp_path / "health.json"
    marker = {"pid": os.getpid(), "heartbeat": 100, "maintenance": 100, "mode": "active"}
    marker.update(changes)
    path.write_text(json.dumps(marker))
    assert not health.healthy(path, now=100)


def test_missing_corrupt_oversized_and_dead_process_markers_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "health.json"
    assert not health.healthy(path)
    for text in ("{", "[]", " " * 1025):
        path.write_text(text)
        assert not health.healthy(path)
    health.HealthWriter(path)(mode="maintenance", maintained=True)
    def missing(pid, signal):
        raise ProcessLookupError()
    monkeypatch.setattr(health.os, "kill", missing)
    assert not health.healthy(path)


def test_cli_uses_only_fixed_local_marker_and_safe_status():
    result = subprocess.run([sys.executable, "-B", "-m", "app.assistant.health"],
        capture_output=True, text=True)
    assert result.returncode in (0, 1)
    assert result.stdout in ("healthy\n", "unhealthy\n")
    assert result.stderr == ""


def test_exited_process_is_unhealthy_even_with_fresh_marker(tmp_path):
    path = tmp_path / "health.json"
    child = subprocess.Popen([sys.executable, "-B", "-c",
        "import sys,time; from app.assistant.health import HealthWriter; "
        "HealthWriter(sys.argv[1])(mode='maintenance',maintained=True); "
        "print('ready',flush=True); time.sleep(30)", str(path)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        assert health.healthy(path)
    finally:
        child.terminate()
        child.wait(timeout=5)
        child.stdout.close()
    assert not health.healthy(path)
