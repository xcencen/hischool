from sqlalchemy import delete, func, or_, select

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.models.notice import Notice, NoticeCategory
from app.models.user import User
from app.schemas.community import NoticeManaged, NoticePublic
from app.services.course_service import commit_changes
from app.services.publication_service import apply_publication, apply_review, check_management_scope, lock_editor, lock_publication


async def categories(db, *, admin=False):
    query = select(NoticeCategory)
    if not admin:
        query = query.where(NoticeCategory.status == 1)
    return [dict(id=row.id, code=row.code, name=row.name, status=row.status)
            for row in (await db.scalars(query.order_by(NoticeCategory.id))).all()]


async def save_category(db, data, actor, category_id=None):
    await lock_editor(db, actor)
    if actor.role != "admin":
        raise BusinessException("无权限管理分类", code=403)
    if category_id:
        row = await db.scalar(select(NoticeCategory).where(NoticeCategory.id == category_id).with_for_update())
        if row is None:
            raise BusinessException("分类不存在", code=404)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
    else:
        row = NoticeCategory(**data.model_dump())
        db.add(row)
    await commit_changes(db)
    return dict(id=row.id, code=row.code, name=row.name, status=row.status)


async def delete_category(db, category_id, actor):
    await lock_editor(db, actor)
    if actor.role != "admin":
        raise BusinessException("无权限管理分类", code=403)
    row = await db.scalar(select(NoticeCategory).where(NoticeCategory.id == category_id).with_for_update())
    if row is None:
        raise BusinessException("分类不存在", code=404)
    if await db.scalar(select(Notice.id).where(Notice.category_id == category_id).with_for_update()):
        raise BusinessException("分类已有关联通知，可停用或先调整通知分类", code=409)
    await db.delete(row)
    await commit_changes(db)


async def valid_category(db, category_id):
    row = await db.scalar(select(NoticeCategory).where(NoticeCategory.id == category_id).with_for_update())
    if row is None or row.status != 1:
        raise BusinessException("请选择启用的通知分类")
    return row


def query_notices():
    return (select(Notice, NoticeCategory.name, User.name)
            .join(NoticeCategory, NoticeCategory.id == Notice.category_id).join(User, User.id == Notice.owner_id))


def response(row, category_name, publisher_name, *, managed=False):
    data = dict(id=row.id, code=row.code, title=row.title, content=row.content, category_id=row.category_id,
                category_name=category_name, publisher_name=publisher_name, published_at=row.published_at)
    if managed:
        return NoticeManaged(**data, owner_id=row.owner_id, state=row.state,
                             revision=row.revision, review_note=row.review_note)
    return NoticePublic(**data)


async def list_notices(db, page=1, page_size=10, q=None, category_id=None, *, actor=None, own_only=False):
    check_management_scope(actor, own_only)
    query = query_notices()
    if actor is None:
        query = query.where(Notice.state == "published", NoticeCategory.status == 1)
    elif own_only:
        query = query.where(Notice.owner_id == actor.id)
    if q and q.strip():
        query = query.where(or_(Notice.title.contains(q.strip(), autoescape=True),
                                Notice.content.contains(q.strip(), autoescape=True)))
    if category_id:
        query = query.where(Notice.category_id == category_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(Notice.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return PageResponse(list=[response(*row, managed=actor is not None) for row in rows], total=total or 0)


async def detail(db, item_id, *, actor=None, own_only=False):
    check_management_scope(actor, own_only)
    query = query_notices().where(Notice.id == item_id)
    if actor is None:
        query = query.where(Notice.state == "published", NoticeCategory.status == 1)
    elif own_only:
        query = query.where(Notice.owner_id == actor.id)
    row = (await db.execute(query)).first()
    if row is None:
        raise BusinessException("通知不存在或尚未发布", code=404)
    return response(*row, managed=actor is not None)


async def create(db, data, actor):
    await lock_editor(db, actor)
    await valid_category(db, data.category_id)
    row = Notice(owner_id=actor.id)
    apply_publication(row, data.model_dump(), actor, creating=True)
    db.add(row)
    await commit_changes(db)
    return await detail(db, row.id, actor=actor, own_only=actor.role != "admin")


async def update(db, item_id, data, actor, *, own_only=False):
    row = await lock_publication(db, Notice, item_id, actor, own_only=own_only)
    values = data.model_dump(exclude_unset=True)
    await valid_category(db, values.get("category_id", row.category_id))
    apply_publication(row, values, actor)
    await commit_changes(db)
    return await detail(db, row.id, actor=actor, own_only=actor.role != "admin")


async def remove(db, item_id, actor, *, own_only=False):
    row = await lock_publication(db, Notice, item_id, actor, own_only=own_only)
    await db.delete(row)
    await commit_changes(db)


async def review(db, item_id, data, actor):
    if actor.role != "admin":
        raise BusinessException("无权限审核", code=403)
    row = await lock_publication(db, Notice, item_id, actor)
    if data.action == "publish":
        await valid_category(db, row.category_id)
    apply_review(row, data)
    await commit_changes(db)
    return await detail(db, row.id, actor=actor)
