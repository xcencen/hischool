"""Authentication contracts that do not require external services."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import jwt
from pydantic import ValidationError
import pytest

from app.config import Settings
from app.schemas.auth import RegisterRequest
from app.schemas.user import UserResponse
from app.utils.jwt import create_access_token, decode_access_token
from app.utils.password import hash_password, validate_password_bytes, verify_password


def settings() -> Settings:
    return Settings(
        database_url="mysql+asyncmy://test:unused@localhost/my_campus_test?charset=utf8mb4",
        redis_url="redis://localhost:6379/15",
        jwt_secret="unit-test-key-only-" * 3,
    )


def test_access_token_has_bound_identity_and_unique_id():
    configuration = settings()
    first = decode_access_token(create_access_token(42, 3, configuration), configuration)
    second = decode_access_token(create_access_token(42, 3, configuration), configuration)
    assert first["sub"] == "42"
    assert first["auth_version"] == 3
    assert first["iss"] == "my-campus"
    assert first["aud"] == "my-campus-web"
    assert first["exp"] > first["iat"]
    assert first["jti"] != second["jti"]
    assert "role" not in first
    assert "password" not in first


def test_token_signed_with_other_key_is_rejected():
    configuration = settings()
    token = create_access_token(42, 0, configuration)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, replace(configuration, jwt_secret="another-test-secret-" * 3))


@pytest.mark.parametrize("change", [
    {"exp": 1},
    {"iss": "another-issuer"},
    {"aud": "another-audience"},
    {"sub": "not-a-user-id"},
    {"auth_version": "0"},
    {"jti": ""},
])
def test_invalid_or_expired_claims_are_rejected(change):
    configuration = settings()
    payload = decode_access_token(create_access_token(42, 0, configuration), configuration)
    payload.update(change)
    token = jwt.encode(payload, configuration.jwt_secret, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, configuration)


@pytest.mark.parametrize("claim", ["sub", "auth_version", "jti", "iat", "exp", "iss", "aud"])
def test_identity_and_lifetime_claims_are_required(claim):
    configuration = settings()
    payload = decode_access_token(create_access_token(42, 0, configuration), configuration)
    payload.pop(claim)
    token = jwt.encode(payload, configuration.jwt_secret, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, configuration)


@pytest.mark.parametrize("password", ["12345678", "a" * 72, "密" * 24])
def test_password_hash_roundtrip_accepts_byte_boundaries(password):
    assert validate_password_bytes(password) == password
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


@pytest.mark.parametrize("password", ["", "a" * 7, "a" * 73, "密" * 25])
def test_password_rejects_outside_bcrypt_byte_limits(password):
    with pytest.raises(ValueError):
        validate_password_bytes(password)
    with pytest.raises(ValidationError):
        RegisterRequest(username="valid_user", password=password)


def test_corrupt_stored_password_is_not_an_authentication_crash():
    assert not verify_password("some-password", "invalid-hash")


def test_public_registration_cannot_set_role_or_status():
    for field, value in (("role", "admin"), ("status", 1)):
        with pytest.raises(ValidationError):
            RegisterRequest(username="valid_user", password="StrongPass-2026", **{field: value})


def test_user_response_never_contains_password_or_auth_version():
    user = SimpleNamespace(
        id=42, username="test_student", name="测试学生", role="student", status=1,
        email=None, phone=None, avatar=None, password="private-hash", auth_version=8,
        create_time=datetime.now(UTC), update_time=datetime.now(UTC),
    )
    response = UserResponse.model_validate(user).model_dump(mode="json")
    assert response["id"] == 42
    assert "password" not in response
    assert "auth_version" not in response
    assert "private-hash" not in str(response)
