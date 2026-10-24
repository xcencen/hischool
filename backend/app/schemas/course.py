from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.schemas.user import Status, StrictRequest

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
CourseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]
PositiveId = Annotated[int, Field(strict=True, ge=1)]


class CourseCreateRequest(StrictRequest):
    """新增课程的请求对象"""

    name: CourseName
    code: Code
    teacher_id: PositiveId
    description: Description | None = None
    status: Status = 1


class CourseUpdateRequest(StrictRequest):
    """更新课程（可选）"""

    name: CourseName | None = None
    code: Code | None = None
    teacher_id: PositiveId | None = None
    description: Description | None = None
    status: Status | None = None

    @field_validator("code", "name", "teacher_id", "status")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("字段不能为空")
        return value


class CourseStudentsRequest(StrictRequest):
    student_ids: list[PositiveId] = Field(max_length=1000)


class PersonOption(BaseModel):
    id: int
    name: str
    username: str


class CourseResponse(BaseModel):
    """课程返回的数据"""

    id: int
    name: str
    code: str
    teacher_id: int
    teacher_name: str
    description: str | None = None
    status: int
