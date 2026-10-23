"""MCP 工具鉴权：从 Authorization 解析并校验 user_id。"""

from app.common.exceptions import BusinessException
from app.database import SessionLocal
from app.models.user import User
from app.utils.jwt import decode_access_token


def user_id_from_authorization(authorization: str | None) -> int:
    """解析 Token 拿到用户 ID"""
    if not authorization:
        raise BusinessException(message="缺少 Authorization", code=401)
    token = authorization
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise BusinessException(message="缺少登录凭证", code=401)
    try:
        payload = decode_access_token(token)
    except Exception:
        raise BusinessException(message="登录已失效，请重新登录", code=401)
    # 获取到用户 ID
    user_id = payload.get("user_id")
    if not user_id:
        raise BusinessException(message="无效的登录凭证", code=401)
    # 从数据库根据用户 ID 查询用户信息
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.status == 1).first()
        if not user:
            raise BusinessException(message="登录已失效或用户已被禁用", code=401)
        return user_id
    finally:
        db.close()
