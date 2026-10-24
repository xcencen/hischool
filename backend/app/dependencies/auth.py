from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BusinessException
from app.database import get_db
from app.models.user import User
from app.utils.jwt import decode_access_token

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise BusinessException("请先登录", code=401)
    try:
        payload = decode_access_token(credentials.credentials, request.app.state.settings)
    except (InvalidTokenError, ValueError, TypeError):
        raise BusinessException("登录已失效，请重新登录", code=401) from None
    try:
        revoked = await request.app.state.redis.exists(f"campus:revoked:{payload['jti']}")
    except RedisError:
        raise BusinessException("认证服务暂不可用，请稍后重试", code=503) from None
    if revoked:
        raise BusinessException("登录已失效，请重新登录", code=401)
    user = await db.scalar(select(User).where(User.id == int(payload["sub"])))
    if user is None or user.status != 1 or user.auth_version != payload["auth_version"]:
        raise BusinessException("登录已失效，请重新登录", code=401)
    request.state.token_payload = payload
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise BusinessException("无权限访问", code=403)
    return current_user


async def get_current_staff(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {"teacher", "admin"}:
        raise BusinessException("无权限维护内容", code=403)
    return current_user
