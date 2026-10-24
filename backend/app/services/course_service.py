"""Async course services shared by HTTP and future MCP tools."""
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BusinessException
from app.models.course import Course
from app.models.enrollment import CourseEnrollment
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.course import CourseCreateRequest, CourseResponse, CourseUpdateRequest, PersonOption
from app.services.user_service import _lock_admins_for_actor


def course_query():
    return select(Course, User.name).join(User, User.id == Course.teacher_id)


def course_response(course: Course, teacher_name: str) -> CourseResponse:
    return CourseResponse(id=course.id, code=course.code, name=course.name,
                          description=course.description, status=course.status,
                          teacher_id=course.teacher_id, teacher_name=teacher_name)


async def list_courses(db: AsyncSession, q: str | None = None, *, admin=False):
    query = course_query()
    if not admin:
        query = query.where(Course.status == 1)
    if q and q.strip():
        query = query.where(or_(Course.name.contains(q.strip(), autoescape=True),
                                Course.code.contains(q.strip(), autoescape=True)))
    return [course_response(course, name) for course, name in
            (await db.execute(query.order_by(Course.code, Course.id))).all()]


async def get_course(db: AsyncSession, course_id: int, *, admin=False):
    query = course_query().where(Course.id == course_id)
    if not admin:
        query = query.where(Course.status == 1)
    row = (await db.execute(query)).first()
    if row is None:
        raise BusinessException("课程不存在或已停用", code=404)
    return course_response(*row)


async def lock_course(db: AsyncSession, course_id: int) -> Course:
    course = await db.scalar(select(Course).where(Course.id == course_id)
                             .with_for_update().execution_options(populate_existing=True))
    if course is None:
        raise BusinessException("课程不存在", code=404)
    return course


async def valid_teacher(db: AsyncSession, teacher_id: int) -> User:
    teacher = await db.scalar(select(User).where(User.id == teacher_id).with_for_update()
                              .execution_options(populate_existing=True))
    if teacher is None or teacher.role != "teacher" or teacher.status != 1:
        raise BusinessException("请选择正常使用的教师账号")
    return teacher


async def commit_changes(db: AsyncSession):
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise BusinessException("数据与已有记录冲突，请刷新后重试", code=409) from None


async def create_course(db: AsyncSession, data: CourseCreateRequest, actor: User):
    # Every admin writer uses the same ordered admin lock. Locking reads after
    # this point see the latest committed rows even under MySQL REPEATABLE READ.
    await _lock_admins_for_actor(db, actor)
    teacher = await valid_teacher(db, data.teacher_id)
    duplicate = await db.scalar(select(Course.id).where(Course.code == data.code).with_for_update())
    if duplicate:
        raise BusinessException("课程编码已存在", code=409)
    course = Course(**data.model_dump())
    db.add(course)
    await commit_changes(db)
    return course_response(course, teacher.name)


async def update_course(db: AsyncSession, course_id: int, data: CourseUpdateRequest, actor: User):
    await _lock_admins_for_actor(db, actor)
    course = await lock_course(db, course_id)
    payload = data.model_dump(exclude_unset=True)
    teacher = await valid_teacher(db, payload.get("teacher_id", course.teacher_id))
    if "code" in payload:
        duplicate = await db.scalar(select(Course.id).where(
            Course.code == payload["code"], Course.id != course_id).with_for_update())
        if duplicate:
            raise BusinessException("课程编码已存在", code=409)
    if teacher.id != course.teacher_id:
        from app.services.schedule_service import check_conflicts
        lessons = (await db.scalars(select(Schedule).where(Schedule.course_id == course_id)
                                    .with_for_update())).all()
        for lesson in lessons:
            await check_conflicts(db, teacher.id, lesson.class_date, lesson.start_time,
                                  lesson.end_time, lesson.location, exclude_course=course_id)
    for key, value in payload.items():
        setattr(course, key, value)
    await commit_changes(db)
    return course_response(course, teacher.name)


async def delete_course(db: AsyncSession, course_id: int, actor: User):
    await _lock_admins_for_actor(db, actor)
    course = await lock_course(db, course_id)
    if await db.scalar(select(Schedule.id).where(Schedule.course_id == course_id).with_for_update()):
        raise BusinessException("课程已有课时，请先删除关联课时或停用课程", code=409)
    await db.execute(delete(CourseEnrollment).where(CourseEnrollment.course_id == course_id))
    await db.delete(course)
    await commit_changes(db)


def person(user: User) -> PersonOption:
    return PersonOption(id=user.id, name=user.name, username=user.username)


async def course_options(db: AsyncSession):
    users = (await db.scalars(select(User).where(User.status == 1, User.role.in_(["teacher", "student"]))
                              .order_by(User.name, User.id))).all()
    return {role + "s": [person(user) for user in users if user.role == role]
            for role in ("teacher", "student")}


async def course_students(db: AsyncSession, course_id: int):
    await get_course(db, course_id, admin=True)
    users = (await db.scalars(select(User).join(CourseEnrollment, CourseEnrollment.user_id == User.id)
                              .where(CourseEnrollment.course_id == course_id).order_by(User.id))).all()
    return [person(user) for user in users]


async def replace_students(db: AsyncSession, course_id: int, student_ids: list[int], actor: User):
    await _lock_admins_for_actor(db, actor)
    await lock_course(db, course_id)
    ids = sorted(set(student_ids))
    users = list((await db.scalars(select(User).where(User.id.in_(ids)).order_by(User.id)
                                   .with_for_update().execution_options(populate_existing=True))).all())
    if len(users) != len(ids) or any(user.role != "student" or user.status != 1 for user in users):
        raise BusinessException("选课名单只接受正常使用的学生账号")
    await db.execute(delete(CourseEnrollment).where(CourseEnrollment.course_id == course_id))
    db.add_all([CourseEnrollment(course_id=course_id, user_id=user_id) for user_id in ids])
    await commit_changes(db)
    return [person(user) for user in users]
