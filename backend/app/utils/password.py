"""Password primitives; callers run bcrypt operations in a thread pool."""

import bcrypt


def validate_password_bytes(password: str) -> str:
    try:
        length = len(password.encode("utf-8"))
    except (AttributeError, UnicodeEncodeError):
        raise ValueError("密码必须是有效的 UTF-8 文本") from None
    if not 8 <= length <= 72:
        raise ValueError("密码长度必须为 8 到 72 个 UTF-8 字节")
    return password


def hash_password(password: str) -> str:
    validate_password_bytes(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        validate_password_bytes(password)
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("ascii"))
    except (ValueError, TypeError, UnicodeError, AttributeError):
        return False
