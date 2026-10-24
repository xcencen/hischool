"""Caller-scoped schedules; class date/time values are Shanghai wall time."""
from datetime import date, datetime, time, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BusinessException
from app.models.course import Course
from app.models.enrollment import CourseEnrollment
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.schedule import ScheduleCreateRequest, ScheduleResponse, ScheduleUpdateRequest, WeekResponse
from app.services.course_service import commit_changes, lock_course, valid_teacher
from app.services.user_service import _lock_admins_for_actor

# Contemporary campus schedules use UTC+08:00, without daylight saving.
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def shanghai_today() -> date:
    return datetime.now(SHANGHAI).date()


def week_bounds(reference: date) -> tuple[date, date]:
    monday = reference - timedelta(days=reference.weekday())
    return monday, monday + timedelta(days=6)


def schedule_query():
    return (select(Schedule, Course, User.name).join(Course, Course.id == Schedule.course_id)
            .join(User, User.id == Course.teacher_id))


def schedule_response(lesson: Schedule, course: Course, teacher_name: str):
    return ScheduleResponse(
        id=lesson.id, course_id=course.id, course_name=course.name, course_code=course.code,
        teacher_id=course.teacher_id, teacher_name=teacher_name, class_date=lesson.class_date,
        start_time=lesson.start_time, end_time=lesson.end_time, period=lesson.period, location=lesson.location)


async def list_schedules(db: AsyncSession, *, user: User | None = None,
                         start: date | None = None, end: date | None = None,
                         course_id: int | None = None):
    query = schedule_query()
    if user is not None:
        query = query.where(Course.status == 1)
        if user.role == "teacher":
            query = query.where(Course.teacher_id == user.id)
        elif user.role == "student":
            query = query.where(select(CourseEnrollment.id).where(
                CourseEnrollment.course_id == Course.id, CourseEnrollment.user_id == user.id).exists())
        else:
            # Admins manage all classes through admin routes, not a synthetic personal timetable.
            query = query.where(False)
    if start:
        query = query.where(Schedule.class_date >= start)
    if end:
        query = query.where(Schedule.class_date <= end)
    if course_id:
        query = query.where(Schedule.course_id == course_id)
    rows = (await db.execute(query.order_by(Schedule.class_date, Schedule.start_time, Schedule.id))).all()
    return [schedule_response(*row) for row in rows]


async def week_schedules(db: AsyncSession, user: User, reference: date):
    start, end = week_bounds(reference)
    return WeekResponse(start_date=start, end_date=end,
                        list=await list_schedules(db, user=user, start=start, end=end))


async def check_conflicts(db: AsyncSession, teacher_id: int, day: date,
                          start: time, end: time, location: str, *,
                          exclude_id: int | None = None, exclude_course: int | None = None):
    query = (select(Schedule.id).join(Course, Course.id == Schedule.course_id)
             .where(Schedule.class_date == day, Schedule.start_time < end, Schedule.end_time > start,
                    or_(Course.teacher_id == teacher_id, Schedule.location == location)))
    if exclude_id is not None:
        query = query.where(Schedule.id != exclude_id)
    if exclude_course is not None:
        query = query.where(Schedule.course_id != exclude_course)
    if await db.scalar(query.with_for_update()):
        raise BusinessException("授课教师或教室的时间与已有课时冲突", code=409)


async def get_schedule(db: AsyncSession, schedule_id: int):
    row = (await db.execute(schedule_query().where(Schedule.id == schedule_id))).first()
    if row is None:
        raise BusinessException("课时不存在", code=404)
    return schedule_response(*row)


async def create_schedule(db: AsyncSession, data: ScheduleCreateRequest, actor: User):
    await _lock_admins_for_actor(db, actor)
    course = await lock_course(db, data.course_id)
    if course.status != 1:
        raise BusinessException("请先启用课程再安排课时")
    await valid_teacher(db, course.teacher_id)
    await check_conflicts(db, course.teacher_id, data.class_date, data.start_time, data.end_time, data.location)
    lesson = Schedule(**data.model_dump())
    db.add(lesson)
    await commit_changes(db)
    return await get_schedule(db, lesson.id)


async def update_schedule(db: AsyncSession, schedule_id: int, data: ScheduleUpdateRequest, actor: User):
    await _lock_admins_for_actor(db, actor)
    lesson = await db.scalar(select(Schedule).where(Schedule.id == schedule_id).with_for_update())
    if lesson is None:
        raise BusinessException("课时不存在", code=404)
    values = {field: getattr(lesson, field) for field in ScheduleCreateRequest.model_fields}
    values.update(data.model_dump(exclude_unset=True))
    try:
        validated = ScheduleCreateRequest.model_validate(values)
    except ValidationError:
        raise BusinessException("课时日期、地点或起止时间无效", code=422) from None
    course = await lock_course(db, validated.course_id)
    if course.status != 1:
        raise BusinessException("请先启用课程再安排课时")
    await valid_teacher(db, course.teacher_id)
    await check_conflicts(db, course.teacher_id, validated.class_date, validated.start_time,
                          validated.end_time, validated.location, exclude_id=schedule_id)
    for key, value in validated.model_dump().items():
        setattr(lesson, key, value)
    await commit_changes(db)
    return await get_schedule(db, schedule_id)


async def delete_schedule(db: AsyncSession, schedule_id: int, actor: User):
    await _lock_admins_for_actor(db, actor)
    lesson = await db.scalar(select(Schedule).where(Schedule.id == schedule_id).with_for_update())
    if lesson is None:
        raise BusinessException("课时不存在", code=404)
    await db.delete(lesson)
    await commit_changes(db)
