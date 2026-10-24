import hashlib
import time

from fastapi import Request
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.common.exceptions import BusinessException
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest
from app.schemas.user import UserResponse
from app.utils.jwt import create_access_token
from app.utils.password import hash_password, verify_password

LOGIN_LIMIT = 20
LOGIN_WINDOW_SECONDS = 60
# A synthetic, non-account hash keeps an unknown username on the same bcrypt
# path as an incorrect password. It is never used to authenticate a user.
_UNKNOWN_USER_HASH = "$2b$12$K2m0/v000utOKiWSNNP0f.03oMhwwNovsIXfwR7iDuN7mLOTEcxxu"
LOGIN_RATE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


async def _limit_login(request: Request, username: str) -> None:
    host = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(f"{host}:{username.lower()}".encode()).hexdigest()
    try:
        count = await request.app.state.redis.eval(
            LOGIN_RATE_SCRIPT, 1, f"campus:login:{digest}", LOGIN_WINDOW_SECONDS
        )
    except RedisError:
        raise BusinessException("认证服务暂不可用，请稍后重试", code=503) from None
    if int(count) > LOGIN_LIMIT:
        raise BusinessException("尝试次数过多，请稍后再试", code=429)


async def login(db: AsyncSession, data: LoginRequest, request: Request) -> LoginResponse:
    await _limit_login(request, data.username)
    user = await db.scalar(select(User).where(User.username == data.username))
    valid = await run_in_threadpool(
        verify_password, data.password, user.password if user is not None else _UNKNOWN_USER_HASH
    )
    if user is None or not valid or user.status != 1:
        raise BusinessException("账号或密码错误", code=401)
    token = create_access_token(user.id, user.auth_version, request.app.state.settings)
    return LoginResponse(token=token, user=UserResponse.model_validate(user))


async def register(db: AsyncSession, data: RegisterRequest) -> UserResponse:
    if await db.scalar(select(User.id).where(User.username == data.username)):
        raise BusinessException("账号已存在", code=409)
    user = User(
        username=data.username, password=await run_in_threadpool(hash_password, data.password),
        name=data.name or data.username, role="student", status=1, auth_version=0,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise BusinessException("账号已存在", code=409) from None
    await db.refresh(user)
    return UserResponse.model_validate(user)


async def logout(request: Request) -> None:
    payload = request.state.token_payload
    remaining = max(1, int(payload["exp"] - time.time()) + 1)
    try:
        stored = await request.app.state.redis.set(
            f"campus:revoked:{payload['jti']}", "1", ex=remaining
        )
    except RedisError:
        raise BusinessException("退出暂未完成，请稍后重试", code=503) from None
    if not stored:
        raise BusinessException("退出暂未完成，请稍后重试", code=503)
