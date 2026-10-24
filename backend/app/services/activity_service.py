"""Moderated activities and transactional, idempotent registration."""
from datetime import UTC, datetime

from sqlalchemy import func, or_, select

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.database import utc_now
from app.models.activity import Activity, ActivityRegistration
from app.models.user import User
from app.schemas.community import ActivityManaged, ActivityPublic, RegistrationResponse
from app.services.course_service import commit_changes
from app.services.publication_service import apply_publication, apply_review, check_management_scope, lock_editor, lock_publication
from app.services.user_service import _lock_current_user


def input_values(data, *, partial=False):
    values = data.model_dump(exclude_unset=partial)
    return {key: value.astimezone(UTC).replace(tzinfo=None) if isinstance(value, datetime) else value
            for key, value in values.items()}


def validate_times(start, end, deadline):
    if end <= start or deadline > start:
        raise BusinessException("报名截止不得晚于开始时间，结束时间须晚于开始时间", code=422)


def query_activities():
    return select(Activity, User.name).join(User, User.id == Activity.owner_id)


def response(row, publisher_name, *, managed=False, registration=None):
    now = utc_now()
    status = registration.status if registration is not None else None
    values = dict(id=row.id, code=row.code, title=row.title, content=row.content,
        publisher_name=publisher_name, published_at=row.published_at, location=row.location,
        start_time=row.start_time, end_time=row.end_time, registration_deadline=row.registration_deadline,
        capacity=row.capacity, enrolled_count=row.enrolled_count, registration_status=status,
        can_register=row.state == "published" and now < row.registration_deadline
            and now < row.start_time and row.enrolled_count < row.capacity and status != "registered",
        can_cancel=status == "registered" and now < row.start_time)
    if managed:
        return ActivityManaged(**values, owner_id=row.owner_id, state=row.state,
                               revision=row.revision, review_note=row.review_note)
    return ActivityPublic(**values)


async def list_activities(db, page=1, page_size=10, q=None, *, actor=None, own_only=False):
    check_management_scope(actor, own_only)
    query = query_activities()
    if actor is None:
        query = query.where(Activity.state == "published")
    elif own_only:
        query = query.where(Activity.owner_id == actor.id)
    if q and q.strip():
        query = query.where(or_(Activity.title.contains(q.strip(), autoescape=True),
                                Activity.content.contains(q.strip(), autoescape=True)))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(Activity.start_time.desc(), Activity.id.desc())
                             .offset((page-1)*page_size).limit(page_size))).all()
    return PageResponse(list=[response(*row, managed=actor is not None) for row in rows], total=total or 0)


async def detail(db, item_id, *, actor=None, own_only=False, viewer=None):
    check_management_scope(actor, own_only)
    query = query_activities().where(Activity.id == item_id)
    if actor is None:
        query = query.where(Activity.state == "published")
    elif own_only:
        query = query.where(Activity.owner_id == actor.id)
    row = (await db.execute(query)).first()
    if row is None:
        raise BusinessException("活动不存在或尚未发布", code=404)
    registration = None
    if viewer is not None:
        registration = await db.scalar(select(ActivityRegistration).where(
            ActivityRegistration.activity_id == item_id, ActivityRegistration.user_id == viewer.id))
    return response(*row, managed=actor is not None, registration=registration)


async def create(db, data, actor):
    await lock_editor(db, actor)
    row = Activity(owner_id=actor.id, enrolled_count=0)
    apply_publication(row, input_values(data), actor, creating=True)
    db.add(row)
    await commit_changes(db)
    return await detail(db, row.id, actor=actor, own_only=actor.role != "admin")


async def update(db, item_id, data, actor, *, own_only=False):
    row = await lock_publication(db, Activity, item_id, actor, own_only=own_only)
    values = input_values(data, partial=True)
    validate_times(values.get("start_time", row.start_time), values.get("end_time", row.end_time),
                   values.get("registration_deadline", row.registration_deadline))
    if values.get("capacity", row.capacity) < row.enrolled_count:
        raise BusinessException("容量不能小于当前有效报名人数", code=409)
    apply_publication(row, values, actor)
    await commit_changes(db)
    return await detail(db, row.id, actor=actor, own_only=actor.role != "admin")


async def remove(db, item_id, actor, *, own_only=False):
    row = await lock_publication(db, Activity, item_id, actor, own_only=own_only)
    if await db.scalar(select(ActivityRegistration.id).where(ActivityRegistration.activity_id == item_id)
                       .with_for_update()):
        raise BusinessException("活动已有报名记录，不能删除；可撤回发布并保留记录", code=409)
    await db.delete(row)
    await commit_changes(db)


async def review(db, item_id, data, actor):
    if actor.role != "admin":
        raise BusinessException("无权限审核", code=403)
    row = await lock_publication(db, Activity, item_id, actor)
    apply_review(row, data)
    await commit_changes(db)
    return await detail(db, row.id, actor=actor)


def registration_response(registration, activity):
    published = activity.state == "published"
    return RegistrationResponse(id=registration.id, activity_id=activity.id,
        status=registration.status, registered_at=registration.registered_at,
        cancelled_at=registration.cancelled_at, activity_title=activity.title if published else "活动暂未发布",
        activity_published=published, start_time=activity.start_time,
        location=activity.location if published else None,
        can_cancel=registration.status == "registered" and utc_now() < activity.start_time)


async def register(db, item_id, actor):
    # Revalidate the caller before locking the activity. All participant writes
    # use user -> activity -> registration order, avoiding inverse admin locks.
    actor = await _lock_current_user(db, actor)
    activity = await db.scalar(select(Activity).where(Activity.id == item_id).with_for_update()
                               .execution_options(populate_existing=True))
    if activity is None:
        raise BusinessException("活动不存在", code=404)
    registration = await db.scalar(select(ActivityRegistration).where(
        ActivityRegistration.activity_id == item_id, ActivityRegistration.user_id == actor.id)
        .with_for_update().execution_options(populate_existing=True))
    # A lost successful response can be retried even if the deadline just passed.
    if registration is not None and registration.status == "registered":
        return registration_response(registration, activity)
    now = utc_now()
    if activity.state != "published":
        raise BusinessException("活动尚未发布", code=404)
    if now >= activity.registration_deadline or now >= activity.start_time:
        raise BusinessException("活动报名已截止", code=409)
    if activity.enrolled_count >= activity.capacity:
        raise BusinessException("活动名额已满", code=409)
    if registration is None:
        registration = ActivityRegistration(activity_id=item_id, user_id=actor.id, status="registered", registered_at=now)
        db.add(registration)
    else:
        registration.status = "registered"
        registration.registered_at = now
        registration.cancelled_at = None
    activity.enrolled_count += 1
    await commit_changes(db)
    return registration_response(registration, activity)


async def cancel(db, item_id, actor):
    actor = await _lock_current_user(db, actor)
    activity = await db.scalar(select(Activity).where(Activity.id == item_id).with_for_update()
                               .execution_options(populate_existing=True))
    if activity is None:
        raise BusinessException("活动不存在", code=404)
    registration = await db.scalar(select(ActivityRegistration).where(
        ActivityRegistration.activity_id == item_id, ActivityRegistration.user_id == actor.id)
        .with_for_update().execution_options(populate_existing=True))
    if registration is None:
        raise BusinessException("没有本人的报名记录", code=404)
    if registration.status == "cancelled":
        return registration_response(registration, activity)
    if utc_now() >= activity.start_time:
        raise BusinessException("活动已开始，不能取消报名", code=409)
    registration.status = "cancelled"
    registration.cancelled_at = utc_now()
    activity.enrolled_count -= 1
    await commit_changes(db)
    return registration_response(registration, activity)


async def my_registrations(db, actor, page=1, page_size=10):
    query = (select(ActivityRegistration, Activity).join(Activity, Activity.id == ActivityRegistration.activity_id)
             .where(ActivityRegistration.user_id == actor.id))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(ActivityRegistration.registered_at.desc(), ActivityRegistration.id.desc())
                             .offset((page-1)*page_size).limit(page_size))).all()
    return PageResponse(list=[registration_response(*row) for row in rows], total=total or 0)
