from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.models.user import User
from app.schemas.user import (
    PasswordUpdateRequest, ProfileUpdateRequest, UserCreateRequest, UserResponse,
    UserUpdateRequest,
)
from app.utils.password import hash_password, verify_password


def get_user_info(user: User) -> UserResponse:
    return UserResponse.model_validate(user)


async def _lock_current_user(db: AsyncSession, user: User) -> User:
    expected_version = user.auth_version
    locked = await db.scalar(
        select(User).where(User.id == user.id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.status != 1 or locked.auth_version != expected_version:
        raise BusinessException("登录已失效，请重新登录", code=401)
    return locked


async def update_user_info(db: AsyncSession, user: User, data: ProfileUpdateRequest) -> UserResponse:
    user = await _lock_current_user(db, user)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field != "name" or value is not None:
            setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


async def update_password(db: AsyncSession, user: User, data: PasswordUpdateRequest) -> None:
    user = await _lock_current_user(db, user)
    if not await run_in_threadpool(verify_password, data.old_password, user.password):
        raise BusinessException("原密码错误", code=400)
    if data.old_password == data.new_password:
        raise BusinessException("新密码不能与原密码相同", code=400)
    user.password = await run_in_threadpool(hash_password, data.new_password)
    user.auth_version += 1
    await db.commit()


async def get_user_page_list(
    db: AsyncSession, page: int, page_size: int, q: str | None = None
) -> PageResponse:
    criteria = []
    if q and q.strip():
        search = f"%{q.strip()}%"
        criteria.append(or_(User.username.like(search), User.name.like(search)))
    total = await db.scalar(select(func.count()).select_from(User).where(*criteria))
    items = (await db.scalars(
        select(User).where(*criteria).order_by(User.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    return PageResponse(list=[UserResponse.model_validate(user) for user in items], total=total or 0)


async def _lock_admins_for_actor(db: AsyncSession, actor: User) -> list[User]:
    # Capture the request's validated credential version before identity-map
    # refresh. Waiting for another admin must not resurrect revoked privileges.
    actor_id, expected_version = actor.id, actor.auth_version
    admins = list((await db.scalars(
        select(User).where(User.role == "admin", User.status == 1).order_by(User.id)
        .with_for_update().execution_options(populate_existing=True)
    )).all())
    current = next((admin for admin in admins if admin.id == actor_id), None)
    if current is None or current.auth_version != expected_version:
        raise BusinessException("登录已失效，请重新登录", code=401)
    return admins


async def create_user(db: AsyncSession, data: UserCreateRequest, actor: User) -> UserResponse:
    await _lock_admins_for_actor(db, actor)
    if await db.scalar(select(User.id).where(User.username == data.username)):
        raise BusinessException("账号已存在", code=409)
    payload = data.model_dump(exclude={"password"})
    payload["name"] = data.name or data.username
    user = User(**payload, password=await run_in_threadpool(hash_password, data.password), auth_version=0)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise BusinessException("账号已存在", code=409) from None
    await db.refresh(user)
    return UserResponse.model_validate(user)


async def update_user(
    db: AsyncSession, user_id: int, data: UserUpdateRequest, actor: User
) -> UserResponse:
    # Lock active admins in a stable order before locking an individual target.
    active_admins = await _lock_admins_for_actor(db, actor)
    user = await db.scalar(
        select(User).where(User.id == user_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise BusinessException("用户不存在", code=404)
    payload = data.model_dump(exclude_unset=True)
    role = payload.get("role") or user.role
    status = payload.get("status") if payload.get("status") is not None else user.status
    removing_admin = user.role == "admin" and user.status == 1 and (role != "admin" or status != 1)
    if removing_admin and len(active_admins) <= 1:
        raise BusinessException("至少保留一个有效管理员", code=409)
    credentials_changed = role != user.role or status != user.status
    for field, value in payload.items():
        if field in {"name", "role", "status"} and value is None:
            continue
        setattr(user, field, value)
    if credentials_changed:
        user.auth_version += 1
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)
