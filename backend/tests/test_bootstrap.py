"""Verify that bootstrap is usable without any legacy service dependencies."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.bootstrap.config import BootstrapSettings, load_settings
from app.main import create_app


def test_health_contract() -> None:
    with TestClient(create_app(BootstrapSettings())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "message": "ok",
        "data": {"name": "my-campus", "version": "0.1.0", "status": "ok"},
    }


def test_only_bootstrap_business_routes_are_mounted() -> None:
    application = create_app(BootstrapSettings())
    assert {
        route.path for route in application.routes if isinstance(route, APIRoute)
    } == {"/", "/api/health"}
    with TestClient(application) as client:
        assert client.get("/uploads/missing.png").status_code == 404
        assert client.post("/api/auth/login", json={}).status_code == 404


def test_bootstrap_settings_use_only_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "test-campus")
    monkeypatch.setenv("APP_VERSION", "0.2.0")
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:4000, ,http://127.0.0.1:4000 ")
    settings = load_settings()

    assert settings == BootstrapSettings(
        app_name="test-campus",
        app_version="0.2.0",
        cors_origins=("http://localhost:4000", "http://127.0.0.1:4000"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/health", headers={"Origin": "http://localhost:4000"}
        )
    assert response.headers["access-control-allow-origin"] == "http://localhost:4000"
    assert response.json()["data"]["name"] == "test-campus"


def test_import_needs_no_legacy_configuration_or_network(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith(("DATABASE_", "JWT_", "REDIS_", "MODEL_", "DASHSCOPE_")):
            environment.pop(name)
    environment["PYTHONPATH"] = str(backend_dir)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    script = textwrap.dedent(
        """
        import importlib.abc
        from pathlib import Path
        import socket
        import sys

        forbidden = (
            'app.config', 'app.database', 'app.models', 'app.api',
            'sqlalchemy', 'pymysql', 'asyncmy', 'redis', 'dotenv',
        )

        class BlockLegacyImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == name or fullname.startswith(name + '.')
                       for name in forbidden):
                    raise AssertionError('Unexpected service import: ' + fullname)
                return None

        def forbid_network(*args, **kwargs):
            raise AssertionError('Bootstrap attempted a network connection')

        sys.meta_path.insert(0, BlockLegacyImports())
        socket.create_connection = forbid_network
        socket.socket.connect = forbid_network
        socket.socket.connect_ex = forbid_network
        before = set(Path.cwd().iterdir())
        from app.main import app, create_app
        assert app.title
        assert create_app().title
        assert set(Path.cwd().iterdir()) == before
        assert not any(name in sys.modules for name in forbidden)
        print('bootstrap-import-ok')
        """
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bootstrap-import-ok"
