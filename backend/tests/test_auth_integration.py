"""HTTP authentication checks against the isolated MySQL/Redis test stack."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CAMPUS_INTEGRATION") != "1",
    reason="Authentication integration needs the dedicated Compose test stack",
)

TEST_PASSWORD = "IntegrationPass-2026"
NEW_PASSWORD = "ChangedIntegration-2026"


@pytest.fixture(scope="module")
def client():
    from sqlalchemy import delete
    from sqlalchemy.engine import make_url
    from app.bootstrap.config import BootstrapSettings
    from app.config import load_settings
    from app.database import Database
    from app.main import create_app
    from app.models.user import User

    configuration = load_settings()
    if make_url(configuration.database_url).database != "my_campus_test":
        pytest.fail("Authentication tests refuse databases other than my_campus_test")
    subprocess.run([sys.executable, "-m", "app.initialize"],
                   cwd=Path(__file__).resolve().parents[1], check=True)
    created_names: list[str] = []
    with TestClient(create_app(BootstrapSettings(), mode="campus")) as http:
        http.created_test_names = created_names
        try:
            yield http
        finally:
            async def cleanup():
                database = Database(configuration.database_url)
                try:
                    async with database.session_factory() as session:
                        if created_names:
                            await session.execute(delete(User).where(User.username.in_(created_names)))
                            await session.commit()
                finally:
                    await database.dispose()
            asyncio.run(cleanup())


def unique_username(client) -> str:
    username = "auth_" + uuid4().hex[:24]
    client.created_test_names.append(username)
    return username


def login(client, username: str, password: str = TEST_PASSWORD) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    assert response.json()["code"] == 200
    return response.json()["data"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def register(client) -> tuple[str, dict]:
    username = unique_username(client)
    response = client.post("/api/auth/register", json={
        "username": username, "password": TEST_PASSWORD, "name": "测试学生",
    })
    assert response.status_code == 200
    return username, login(client, username)


@pytest.fixture(scope="module")
def admin_headers(client):
    response = login(client, "demo_admin", os.environ["CAMPUS_DEMO_ADMIN_PASSWORD"])
    assert response["user"]["role"] == "admin"
    return bearer(response["token"])


def test_registration_identity_and_duplicate_conflict(client):
    username, authentication = register(client)
    assert authentication["user"]["role"] == "student"
    assert "password" not in authentication["user"]
    assert "auth_version" not in authentication["user"]
    duplicate = client.post("/api/auth/register", json={"username": username, "password": TEST_PASSWORD})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == 409
    assert TEST_PASSWORD not in duplicate.text


def test_public_requests_cannot_allocate_privileges(client):
    username = unique_username(client)
    response = client.post("/api/auth/register", json={
        "username": username, "password": TEST_PASSWORD, "role": "admin",
    })
    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert TEST_PASSWORD not in response.text
    invalid = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    assert invalid.status_code == 401


def test_me_requires_authentication_and_is_scoped_to_caller(client):
    assert client.get("/api/user/me").status_code == 401
    _, first = register(client)
    _, second = register(client)
    response = client.get("/api/user/me", params={"user_id": second["user"]["id"]},
                          headers=bearer(first["token"]))
    assert response.status_code == 200
    assert response.json()["data"]["id"] == first["user"]["id"]
    forbidden = client.patch("/api/user/me", headers=bearer(first["token"]), json={"role": "admin"})
    assert forbidden.status_code == 422


def test_profile_update_persists_without_changing_role(client):
    _, authentication = register(client)
    headers = bearer(authentication["token"])
    response = client.patch("/api/user/me", headers=headers,
                            json={"name": "资料已更新", "email": "test@example.invalid", "phone": "13800000000"})
    assert response.status_code == 200
    profile = client.get("/api/user/me", headers=headers).json()["data"]
    assert profile["name"] == "资料已更新"
    assert profile["email"] == "test@example.invalid"
    assert profile["role"] == "student"
    assert "password" not in profile


def test_claimed_role_cannot_override_database_permissions(client):
    import jwt
    from app.config import load_settings
    from app.utils.jwt import decode_access_token

    _, authentication = register(client)
    configuration = load_settings()
    payload = decode_access_token(authentication["token"], configuration)
    payload["role"] = "admin"
    token = jwt.encode(payload, configuration.jwt_secret, algorithm="HS256")
    response = client.get("/api/admin/users", headers=bearer(token))
    # A stricter claim validator may reject extra claims outright; neither path
    # may grant the privilege claimed by the caller.
    assert response.status_code in {401, 403}


def test_revocation_store_failure_denies_access(client, monkeypatch):
    from unittest.mock import AsyncMock
    from redis.exceptions import RedisError

    _, authentication = register(client)
    for method in ("get", "exists"):
        monkeypatch.setattr(client.app.state.redis, method, AsyncMock(side_effect=RedisError("injected outage")))
    response = client.get("/api/user/me", headers=bearer(authentication["token"]))
    assert response.status_code == 503
    assert response.json()["code"] == 503


def test_logout_revokes_the_existing_token(client):
    _, authentication = register(client)
    headers = bearer(authentication["token"])
    response = client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 200
    assert client.get("/api/user/me", headers=headers).status_code == 401
    assert client.post("/api/auth/logout", headers=headers).status_code == 401


def test_password_change_requires_old_password_and_invalidates_old_token(client):
    username, authentication = register(client)
    headers = bearer(authentication["token"])
    denied = client.post("/api/user/me/password", headers=headers,
                         json={"old_password": "IncorrectPass-2026", "new_password": NEW_PASSWORD})
    assert denied.status_code in {400, 401}
    assert client.get("/api/user/me", headers=headers).status_code == 200
    changed = client.post("/api/user/me/password", headers=headers,
                          json={"old_password": TEST_PASSWORD, "new_password": NEW_PASSWORD})
    assert changed.status_code == 200
    assert client.get("/api/user/me", headers=headers).status_code == 401
    old_login = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    assert old_login.status_code == 401
    assert login(client, username, NEW_PASSWORD)["user"]["username"] == username


def test_admin_assigns_roles_and_disables_accounts_with_token_invalidation(client, admin_headers):
    username, authentication = register(client)
    assert client.get("/api/admin/users", headers=bearer(authentication["token"])).status_code == 403
    assigned = client.patch(f"/api/admin/users/{authentication['user']['id']}",
                           headers=admin_headers, json={"role": "teacher"})
    assert assigned.status_code == 200
    assert client.get("/api/user/me", headers=bearer(authentication["token"])).status_code == 401
    teacher = login(client, username)
    assert teacher["user"]["role"] == "teacher"
    assert client.get("/api/admin/users", headers=bearer(teacher["token"])).status_code == 403
    disabled = client.patch(f"/api/admin/users/{teacher['user']['id']}",
                           headers=admin_headers, json={"status": 0})
    assert disabled.status_code == 200
    assert client.get("/api/user/me", headers=bearer(teacher["token"])).status_code == 401
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 401


def test_admin_can_create_teacher_and_search_without_returning_password(client, admin_headers):
    username = unique_username(client)
    response = client.post("/api/admin/users", headers=admin_headers, json={
        "username": username, "password": TEST_PASSWORD, "name": "演示教师", "role": "teacher", "status": 1,
    })
    assert response.status_code == 200
    teacher = login(client, username)
    assert teacher["user"]["role"] == "teacher"
    users = client.get("/api/admin/users", headers=admin_headers, params={"q": username}).json()["data"]
    assert users["total"] == 1
    assert users["list"][0]["username"] == username
    assert "password" not in users["list"][0]
    assert "auth_version" not in users["list"][0]


def test_last_active_admin_cannot_be_disabled_or_demoted(client, admin_headers):
    administrator = client.get("/api/user/me", headers=admin_headers).json()["data"]
    for change in ({"status": 0}, {"role": "student"}):
        response = client.patch(f"/api/admin/users/{administrator['id']}", headers=admin_headers, json=change)
        assert response.status_code == 409
        assert response.json()["code"] == 409
    assert client.get("/api/admin/users", headers=admin_headers).status_code == 200


def test_repeated_bad_logins_are_rate_limited(client):
    username = unique_username(client)
    for _ in range(20):
        response = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
        assert response.status_code == 401
    response = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    assert response.status_code == 429
    assert response.json()["code"] == 429


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("revocation", ["role", "status", "version"])
def test_stale_admin_identity_cannot_write_after_revocation(client, admin_headers, operation, revocation):
    """Model a dependency read that preceded another transaction's revocation.

    This deliberately uses two real DB sessions rather than claiming to be a
    full concurrent HTTP or lock-wait test. The write service must revalidate
    the stale ORM identity against committed database state before it writes.
    """
    from sqlalchemy import delete, select, update
    from app.common.exceptions import BusinessException
    from app.config import load_settings
    from app.database import Database
    from app.models.user import User
    from app.schemas.user import UserCreateRequest, UserUpdateRequest
    from app.services import user_service

    actor_name = unique_username(client)
    actor_response = client.post("/api/admin/users", headers=admin_headers, json={
        "username": actor_name, "password": TEST_PASSWORD, "name": "临时管理员", "role": "admin", "status": 1,
    })
    assert actor_response.status_code == 200
    target_name, target = register(client)
    target_id = target["user"]["id"]
    attempted_name = unique_username(client)

    async def check():
        database = Database(load_settings().database_url)
        try:
            async with database.session_factory() as original_session:
                actor = await original_session.scalar(select(User).where(User.username == actor_name))
                assert actor is not None and actor.role == "admin" and actor.status == 1
                old_version = actor.auth_version
                changes = {"auth_version": old_version + 1}
                if revocation == "role":
                    changes["role"] = "student"
                elif revocation == "status":
                    changes["status"] = 0
                async with database.session_factory() as revoking_session:
                    await revoking_session.execute(update(User).where(User.id == actor.id).values(**changes))
                    await revoking_session.commit()
                # A different session's commit must not mutate this cached ORM
                # object. This is the exact stale state the service must reject.
                assert actor.role == "admin" and actor.status == 1
                assert actor.auth_version == old_version
                with pytest.raises(BusinessException) as denied:
                    if operation == "create":
                        await user_service.create_user(original_session, UserCreateRequest(
                            username=attempted_name, password=TEST_PASSWORD, name="禁止创建", role="admin",
                        ), actor=actor)
                    else:
                        await user_service.update_user(original_session, target_id, UserUpdateRequest(
                            name="禁止修改", role="admin",
                        ), actor=actor)
                assert denied.value.code == 401
                await original_session.rollback()
            async with database.session_factory() as verifying_session:
                assert await verifying_session.scalar(select(User.id).where(User.username == attempted_name)) is None
                actual = await verifying_session.scalar(select(User).where(User.id == target_id))
                assert actual is not None
                assert actual.name == target["user"]["name"]
                assert actual.role == "student"
        finally:
            # These names belong only to this case; leave all demo users intact.
            async with database.session_factory() as cleanup_session:
                await cleanup_session.execute(delete(User).where(User.username.in_(
                    [actor_name, target_name, attempted_name]
                )))
                await cleanup_session.commit()
            await database.dispose()

    asyncio.run(check())
