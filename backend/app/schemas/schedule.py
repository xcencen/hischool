from datetime import date

from pydantic import BaseModel, ConfigDict


class ScheduleCreateRequest(BaseModel):
    """管理员新增课表。"""

    user_id: int
    class_date: date
    period: str
    course_id: int
    location: str

    model_config = ConfigDict(str_strip_whitespace=True)


class ScheduleUpdateRequest(BaseModel):
    """管理员更新课表。"""

    user_id: int | None = None
    class_date: date | None = None
    period: str | None = None
    course_id: int | None = None
    location: str | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class ScheduleResponse(BaseModel):
    """课表返回（联表带出账号、姓名、课程名，方便页面直接展示）。"""

    id: int
    user_id: int
    username: str
    user_name: str
    class_date: date
    period: str
    course_id: int
    course_name: str
    location: str

    model_config = ConfigDict(from_attributes=True)
