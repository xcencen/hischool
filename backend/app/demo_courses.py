"""Repeatable demo content; never replace administrator edits."""
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.enrollment import CourseEnrollment
from app.models.schedule import Schedule
from app.models.user import User
from app.services.schedule_service import shanghai_today, week_bounds


async def ensure_demo_courses(session: AsyncSession, *, today: date | None = None):
    teacher = await session.scalar(select(User).where(User.username == "demo_teacher"))
    student = await session.scalar(select(User).where(User.username == "demo_student"))
    if teacher is None or teacher.role != "teacher" or teacher.status != 1:
        return
    monday, _ = week_bounds(today or shanghai_today())
    for code, name, lessons in (
        ("DEMO-CS101", "Python 程序设计", [(0, time(8), time(9, 30), "1-2", "教学楼 A101"),
                                        (2, time(10), time(11, 30), "3-4", "实验楼 B201")]),
        ("DEMO-CS102", "数据库原理", [(4, time(14), time(15, 30), "5-6", "教学楼 A203")]),
    ):
        existing = await session.scalar(select(Course).where(Course.code == code))
        if existing is None:
            statement = insert(Course).values(code=code, name=name, teacher_id=teacher.id,
                description="校园服务演示课程，使用模拟教学数据。", status=1)
            await session.execute(statement.on_duplicate_key_update(id=Course.id))
        course = await session.scalar(select(Course).where(Course.code == code))
        if student is not None and student.role == "student" and student.status == 1:
            # Only seed the enrollment when the course was first created.
            # Later removal/replacement by an admin must remain intact.
            if existing is None:
                statement = insert(CourseEnrollment).values(course_id=course.id, user_id=student.id)
                await session.execute(statement.on_duplicate_key_update(id=CourseEnrollment.id))
        if course.status != 1 or course.teacher_id != teacher.id:
            continue
        week_exists = await session.scalar(select(Schedule.id).where(
            Schedule.course_id == course.id, Schedule.class_date >= monday,
            Schedule.class_date <= monday + timedelta(days=6)))
        if week_exists is not None:
            continue
        for offset, start, end, period, location in lessons:
            day = monday + timedelta(days=offset)
            statement = insert(Schedule).values(course_id=course.id, class_date=day,
                start_time=start, end_time=end, period=period, location=location)
            await session.execute(statement.on_duplicate_key_update(id=Schedule.id))
    await session.flush()
