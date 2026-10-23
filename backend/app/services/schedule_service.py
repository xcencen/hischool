from datetime import date

from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.models.course import Course
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.schedule import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleUpdateRequest,
)


def _to_response(
    row: Schedule,
    username: str,
    user_name: str,
    course_name: str,
) -> ScheduleResponse:
    """把课表行 + 联表字段组装成响应。"""
    return ScheduleResponse(
        id=row.id,
        user_id=row.user_id,
        username=username,
        user_name=user_name,
        class_date=row.class_date,
        period=row.period,
        course_id=row.course_id,
        course_name=course_name,
        location=row.location,
    )


def _base_query(
    db: Session, user_id: int | None = None, class_date: date | None = None
):
    query = (
        db.query(Schedule, User.username, User.name, Course.name)
        .join(User, Schedule.user_id == User.id)
        .join(Course, Schedule.course_id == Course.id)
    )
    if user_id is not None:
        query = query.filter(Schedule.user_id == user_id)
    if class_date is not None:
        query = query.filter(Schedule.class_date == class_date)
    return query


def list_page_schedules(
    db: Session,
    user_id: int | None = None,
    class_date: date | None = None,
    page: int = 1,
    page_size: int = 10,
) -> PageResponse:
    """分页查询课表列表"""
    query = _base_query(db, user_id, class_date)
    total = query.count()
    rows = (
        query.order_by(Schedule.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[
            _to_response(
                row=row, username=username, user_name=user_name, course_name=course_name
            )
            for row, username, user_name, course_name in rows
        ],
        total=total,
    )


def list_schedules(
    db: Session,
    user_id: int | None = None,
    class_date: date | None = None,
) -> list[ScheduleResponse]:
    """查询全部课表列表 —— MCP 工具使用"""
    rows = _base_query(db, user_id, class_date).order_by(Schedule.id.desc()).all()
    return [
        _to_response(
            row=row, username=username, user_name=user_name, course_name=course_name
        )
        for row, username, user_name, course_name in rows
    ]


def create_schedule(db: Session, data: ScheduleCreateRequest) -> ScheduleResponse:
    """新增课表"""
    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise BusinessException(message="用户不存在")
    if user.role != "student":
        raise BusinessException(message="只能给学生安排课表")

    course = db.query(Course).filter(Course.id == data.course_id).first()
    if not course:
        raise BusinessException(message="课程不存在")

    row = Schedule(**data.model_dump())  # {} -> key1=value1, key2=value2
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_response(row, user.username, user.name, course.name)


def update_schedule(
    db: Session, schedule_id: int, data: ScheduleUpdateRequest
) -> ScheduleResponse:
    """更新课表"""
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise BusinessException(message="课表不存在")
    payload = data.model_dump(exclude_none=True)
    user_id = payload.get("user_id", row.user_id)
    course_id = payload.get("course_id", row.course_id)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise BusinessException(message="用户不存在")
    if user.role != "student":
        raise BusinessException(message="只能给学生安排课表")

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise BusinessException(message="课程不存在")

    for field, value in payload.items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return _to_response(row, user.username, user.name, course.name)


def delete_schedule(db: Session, schedule_id: int) -> None:
    """删除课表"""
    row = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not row:
        raise BusinessException(message="课表不存在")
    db.delete(row)
    db.commit()


def list_schedules_as_dict(
    db: Session,
    user_id: int | None = None,
    date_str: str | None = None,  # YYYY-MM-DD
) -> list[dict]:
    """查询全部课表列表 返回字典列表 MCP 工具使用"""
    date_text = (date_str or "").strip()
    class_date = date.fromisoformat(date_text) if date_text else None
    items = list_schedules(db, user_id, class_date)
    return [
        {
            "date": item.class_date.isoformat(),  # date -> str: YYYY-MM-DD
            "period": item.period,
            "course_id": item.course_id,
            "course_name": item.course_name,
            "location": item.location,
        }
        for item in items
    ]
