"""Access tokens with explicit settings and no import-time configuration."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt

from app.config import Settings

ISSUER = "my-campus"
AUDIENCE = "my-campus-web"


def create_access_token(user_id: int, auth_version: int, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id), "auth_version": auth_version,
            "jti": uuid4().hex, "iat": now,
            "exp": now + timedelta(hours=settings.jwt_expire_hours),
            "iss": ISSUER, "aud": AUDIENCE,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
        issuer=ISSUER, audience=AUDIENCE,
        options={"require": ["sub", "auth_version", "jti", "iat", "exp", "iss", "aud"]},
    )
    subject = payload.get("sub")
    version = payload.get("auth_version")
    token_id = payload.get("jti")
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdigit() or int(subject) < 1:
        raise jwt.InvalidTokenError("Invalid token subject")
    if type(version) is not int or version < 0:
        raise jwt.InvalidTokenError("Invalid credential version")
    if not isinstance(token_id, str) or not 1 <= len(token_id) <= 128:
        raise jwt.InvalidTokenError("Invalid token identifier")
    if type(payload["iat"]) is not int or type(payload["exp"]) is not int:
        raise jwt.InvalidTokenError("Invalid token timestamps")
    return payload
