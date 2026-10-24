from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_serializer, field_validator

from app.utils.password import validate_password_bytes

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_]+$")]
Password = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(validate_password_bytes)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Contact = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]
Role = Literal["student", "teacher", "admin"]
Status = Annotated[int, Field(strict=True, ge=0, le=1)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: Role
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    status: int
    create_time: datetime | None = None
    update_time: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("create_time", "update_time")
    def utc_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


class ProfileUpdateRequest(StrictRequest):
    name: Name | None = None
    email: Contact | None = None
    phone: Contact | None = None

    @field_validator("email", "phone", mode="before")
    @classmethod
    def blank_contact(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class UserCreateRequest(StrictRequest):
    username: Username
    password: Password
    name: Name | None = None
    email: Contact | None = None
    phone: Contact | None = None
    role: Role = "student"
    status: Status = 1


class UserUpdateRequest(ProfileUpdateRequest):
    role: Role | None = None
    status: Status | None = None


class PasswordUpdateRequest(StrictRequest):
    old_password: Password
    new_password: Password
