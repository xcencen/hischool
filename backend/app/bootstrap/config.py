"""Read only bootstrap settings from the process environment.

The legacy .env file is deliberately not loaded. Database, Redis, model services,
and upload directories are not needed to import or run this application.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapSettings:
    app_name: str = "my-campus"
    app_version: str = "0.1.0"
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


def load_settings() -> BootstrapSettings:
    defaults = BootstrapSettings()
    origins = os.environ.get("CORS_ORIGINS", ",".join(defaults.cors_origins))
    return BootstrapSettings(
        app_name=os.environ.get("APP_NAME", defaults.app_name).strip()
        or defaults.app_name,
        app_version=os.environ.get("APP_VERSION", defaults.app_version).strip()
        or defaults.app_version,
        cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
    )
