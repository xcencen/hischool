"""Shared authorization and moderation rules, reusable by future MCP tools."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BusinessException
from app.database import utc_now
from app.models.user import User
from app.schemas.community import ReviewRequest
from app.services.user_service import _lock_admins_for_actor, _lock_current_user


def check_management_scope(actor: User | None, own_only: bool):
    if actor is not None and (actor.role not in {"teacher", "admin"}
                              or (not own_only and actor.role != "admin")):
        raise BusinessException("无权限读取管理内容", code=403)


async def lock_editor(db: AsyncSession, actor: User):
    if actor.role == "admin":
        await _lock_admins_for_actor(db, actor)
    elif actor.role == "teacher":
        fresh = await _lock_current_user(db, actor)
        if fresh.role != "teacher":
            raise BusinessException("无权限维护内容", code=403)
    else:
        raise BusinessException("无权限维护内容", code=403)


async def lock_publication(db, model, item_id: int, actor: User, *, own_only=False):
    await lock_editor(db, actor)
    row = await db.scalar(select(model).where(model.id == item_id).with_for_update()
                           .execution_options(populate_existing=True))
    if row is None:
        raise BusinessException("内容不存在", code=404)
    if (own_only or actor.role != "admin") and row.owner_id != actor.id:
        raise BusinessException("只能维护本人发布的内容", code=403)
    return row


def publication_state(actor: User, desired: str):
    if desired == "published" and actor.role != "admin":
        raise BusinessException("教师内容须由管理员审核发布", code=403)
    return desired


def apply_publication(row, values: dict, actor: User, *, creating=False):
    desired = values.pop("state", "pending" if actor.role == "teacher" else row.state)
    state = publication_state(actor, desired)
    for field, value in values.items():
        setattr(row, field, value)
    row.state = state
    row.review_note = None
    row.published_at = utc_now() if state == "published" else None
    row.revision = 1 if creating else row.revision + 1


def apply_review(row, data: ReviewRequest):
    if row.state != "pending" or row.revision != data.expected_revision:
        raise BusinessException("内容已变化，请刷新后重新审核", code=409)
    row.state = "published" if data.action == "publish" else "rejected"
    row.review_note = data.note or None
    row.published_at = utc_now() if row.state == "published" else None
    row.revision += 1
