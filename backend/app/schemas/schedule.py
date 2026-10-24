from datetime import date, time
from typing import Annotated

from pydantic import BaseModel, StringConstraints, field_validator, model_validator

from app.schemas.course import PositiveId
from app.schemas.user import StrictRequest

Period = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ScheduleUpdateRequest(StrictRequest):
    course_id: PositiveId | None = None
    class_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    period: Period | None = None
    location: Location | None = None

    @field_validator("course_id", "class_date", "start_time", "end_time", "period", "location")
    @classmethod
    def non_null_local(cls, value):
        if value is None:
            raise ValueError("字段不能为空")
        if isinstance(value, time) and (value.tzinfo is not None or value.microsecond):
            raise ValueError("课时应为北京时间，精确到秒且不带时区")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class ScheduleCreateRequest(ScheduleUpdateRequest):
    course_id: PositiveId
    class_date: date
    start_time: time
    end_time: time
    period: Period
    location: Location


class ScheduleResponse(BaseModel):
    id: int
    course_id: int
    course_name: str
    course_code: str
    teacher_id: int
    teacher_name: str
    class_date: date
    start_time: time
    end_time: time
    period: str
    location: str


class WeekResponse(BaseModel):
    start_date: date
    end_date: date
    list: list[ScheduleResponse]
