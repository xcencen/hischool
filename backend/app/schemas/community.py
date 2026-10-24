from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, field_serializer, field_validator, model_validator

from app.schemas.course import Code, PositiveId
from app.schemas.user import Status, StrictRequest

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
State = Literal["draft", "pending", "published"]
Capacity = Annotated[int, Field(strict=True, ge=1, le=100000)]


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(aware_utc)]


class CommunityResponse(BaseModel):
    @field_serializer("published_at", "start_time", "end_time", "registration_deadline",
                      "registered_at", "cancelled_at", check_fields=False)
    def utc_timestamp(self, value: datetime | None) -> str | None:
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if value else None


class CategoryCreate(StrictRequest):
    code: Code
    name: CategoryName
    status: Status = 1


class CategoryUpdate(StrictRequest):
    name: CategoryName | None = None
    status: Status | None = None

    @field_validator("*")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("字段不能为空")
        return value


class PublicationCreate(StrictRequest):
    code: Code
    title: Title
    content: Content
    state: State = "pending"


class PublicationUpdate(StrictRequest):
    title: Title | None = None
    content: Content | None = None
    state: State | None = None

    @field_validator("*")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("字段不能为空")
        return value


class NoticeCreate(PublicationCreate):
    category_id: PositiveId


class NoticeUpdate(PublicationUpdate):
    category_id: PositiveId | None = None


class ActivityCreate(PublicationCreate):
    location: Location
    start_time: UtcDateTime
    end_time: UtcDateTime
    registration_deadline: UtcDateTime
    capacity: Capacity

    @model_validator(mode="after")
    def ordered(self):
        if self.end_time <= self.start_time or self.registration_deadline > self.start_time:
            raise ValueError("报名截止不得晚于开始时间，结束时间须晚于开始时间")
        return self


class ActivityUpdate(PublicationUpdate):
    location: Location | None = None
    start_time: UtcDateTime | None = None
    end_time: UtcDateTime | None = None
    registration_deadline: UtcDateTime | None = None
    capacity: Capacity | None = None


class ReviewRequest(StrictRequest):
    expected_revision: PositiveId
    action: Literal["publish", "reject"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""

    @model_validator(mode="after")
    def reason_required(self):
        if self.action == "reject" and not self.note:
            raise ValueError("退回时请填写原因")
        return self


class NoticePublic(CommunityResponse):
    id: int
    code: str
    title: str
    content: str
    category_id: int
    category_name: str
    publisher_name: str
    published_at: datetime | None


class NoticeManaged(NoticePublic):
    owner_id: int
    state: str
    revision: int
    review_note: str | None


class ActivityPublic(CommunityResponse):
    id: int
    code: str
    title: str
    content: str
    publisher_name: str
    published_at: datetime | None
    location: str
    start_time: datetime
    end_time: datetime
    registration_deadline: datetime
    capacity: int
    enrolled_count: int
    registration_status: str | None = None
    can_register: bool = False
    can_cancel: bool = False


class ActivityManaged(ActivityPublic):
    owner_id: int
    state: str
    revision: int
    review_note: str | None


class RegistrationResponse(CommunityResponse):
    id: int
    activity_id: int
    status: str
    registered_at: datetime
    cancelled_at: datetime | None
    activity_title: str
    activity_published: bool
    start_time: datetime
    location: str | None
    can_cancel: bool
