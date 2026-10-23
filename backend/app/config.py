"""Explicit campus configuration; importing this module never reads a .env file."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


ALLOWED_DATABASE_NAMES = frozenset({"my_campus", "my_campus_test"})


def validate_database_url(raw: str) -> str:
    """Reject legacy databases before an engine or connection can be created."""
    try:
        url = make_url(raw)
    except (ArgumentError, TypeError, ValueError):
        raise ValueError("CAMPUS_DATABASE_URL is not a valid MySQL URL") from None
    if url.drivername != "mysql+asyncmy":
        raise ValueError("CAMPUS_DATABASE_URL must use mysql+asyncmy")
    if url.database not in ALLOWED_DATABASE_NAMES:
        raise ValueError("CAMPUS_DATABASE_URL must target my_campus or my_campus_test")
    if not url.host:
        raise ValueError("CAMPUS_DATABASE_URL must include a host")
    # Driver query options such as db or init_command can otherwise redirect the
    # selected schema after this guard. Only the documented charset is accepted.
    if set(url.query) - {"charset"} or url.query.get("charset", "utf8mb4") != "utf8mb4":
        raise ValueError("CAMPUS_DATABASE_URL only permits charset=utf8mb4 as a query option")
    return raw


def _validate_redis_url(raw: str) -> None:
    try:
        parsed = urlsplit(raw)
        valid = parsed.scheme in {"redis", "rediss"} and bool(parsed.hostname)
        parsed.port
    except ValueError:
        raise ValueError("CAMPUS_REDIS_URL is not a valid Redis URL") from None
    if not valid:
        raise ValueError("CAMPUS_REDIS_URL must use redis:// or rediss:// and a host")


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    redis_url: str = field(repr=False)
    jwt_secret: str = field(repr=False)
    jwt_expire_hours: int = 24
    jwt_algorithm: str = "HS256"

    def __post_init__(self) -> None:
        validate_database_url(self.database_url)
        _validate_redis_url(self.redis_url)
        if len(self.jwt_secret) < 32:
            raise ValueError("CAMPUS_JWT_SECRET must contain at least 32 characters")
        if self.jwt_algorithm != "HS256":
            raise ValueError("CAMPUS_JWT_ALGORITHM must be HS256")
        if type(self.jwt_expire_hours) is not int or not 1 <= self.jwt_expire_hours <= 168:
            raise ValueError("CAMPUS_JWT_EXPIRE_HOURS must be between 1 and 168")


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load process variables only, and only when campus mode explicitly asks."""
    source = os.environ if environ is None else environ
    required = ("CAMPUS_DATABASE_URL", "CAMPUS_REDIS_URL", "CAMPUS_JWT_SECRET")
    missing = [name for name in required if not source.get(name)]
    if missing:
        raise ValueError("Missing campus configuration: " + ", ".join(missing))
    try:
        expires = int(source.get("CAMPUS_JWT_EXPIRE_HOURS", "24"))
    except ValueError:
        raise ValueError("CAMPUS_JWT_EXPIRE_HOURS must be an integer") from None
    return Settings(
        database_url=source["CAMPUS_DATABASE_URL"],
        redis_url=source["CAMPUS_REDIS_URL"],
        jwt_secret=source["CAMPUS_JWT_SECRET"],
        jwt_expire_hours=expires,
        jwt_algorithm=source.get("CAMPUS_JWT_ALGORITHM", "HS256"),
    )
