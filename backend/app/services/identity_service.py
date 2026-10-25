"""Current campus identity checks shared by HTTP and private service calls."""

import time

from redis.exceptions import RedisError
from sqlalchemy import select

from app.common.exceptions import BusinessException
from app.models.user import User


async def active_identity(db, redis, *, user_id, auth_version, session_jti, expires_at=None):
    if expires_at is not None and time.time() >= expires_at:
        raise BusinessException("登录已失效，请重新登录", code=401)
    try:
        revoked = await redis.exists(f"campus:revoked:{session_jti}")
    except RedisError:
        raise BusinessException("认证服务暂不可用，请稍后重试", code=503) from None
    if revoked:
        raise BusinessException("登录已失效，请重新登录", code=401)
    user = await db.scalar(select(User).where(User.id == user_id)
                           .execution_options(populate_existing=True))
    if user is None or user.status != 1 or user.auth_version != auth_version:
        raise BusinessException("登录已失效，请重新登录", code=401)
    return user
