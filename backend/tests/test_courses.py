"""Course and timetable input/date contracts without external services."""

from datetime import UTC, date, datetime, time

from pydantic import ValidationError
import pytest

from app.schemas.course import CourseCreateRequest, CourseStudentsRequest
from app.schemas.schedule import ScheduleCreateRequest
from app.services import schedule_service


def course_payload(**changes):
    return {"code": "TEST-CS101", "name": "课程测试", "teacher_id": 1, **changes}


def schedule_payload(**changes):
    return {
        "course_id": 1, "class_date": "2030-01-07", "start_time": "08:00:00",
        "end_time": "09:30:00", "period": "1-2", "location": "教学楼101", **changes,
    }


@pytest.mark.parametrize("change", [
    {"code": " "}, {"code": "a" * 51}, {"name": " "}, {"name": "a" * 101},
    {"teacher_id": 0}, {"status": 2}, {"user_id": 1},
])
def test_course_rejects_invalid_fields(change):
    with pytest.raises(ValidationError):
        CourseCreateRequest.model_validate(course_payload(**change))


@pytest.mark.parametrize("change", [
    {"start_time": "10:00:00", "end_time": "09:00:00"},
    {"end_time": "08:00:00"},
    {"start_time": "08:00:00+08:00"},
    {"class_date": "not-a-date"},
    {"course_id": 0}, {"period": " "}, {"location": " "}, {"user_id": 1},
])
def test_schedule_rejects_invalid_intervals_or_legacy_identity(change):
    with pytest.raises(ValidationError):
        ScheduleCreateRequest.model_validate(schedule_payload(**change))


def test_schedule_accepts_local_classroom_times():
    data = ScheduleCreateRequest.model_validate(schedule_payload())
    assert data.class_date == date(2030, 1, 7)
    assert data.start_time == time(8)
    assert data.end_time == time(9, 30)
    assert data.start_time.tzinfo is None


def test_enrollment_identity_requires_positive_ids():
    with pytest.raises(ValidationError):
        CourseStudentsRequest(student_ids=[0])


@pytest.mark.parametrize("reference,start,end", [
    (date(2026, 10, 24), date(2026, 10, 19), date(2026, 10, 25)),
    (date(2026, 10, 25), date(2026, 10, 19), date(2026, 10, 25)),
    (date(2026, 10, 26), date(2026, 10, 26), date(2026, 11, 1)),
    (date(2026, 1, 1), date(2025, 12, 29), date(2026, 1, 4)),
])
def test_week_bounds_include_monday_through_sunday(reference, start, end):
    assert schedule_service.week_bounds(reference) == (start, end)


def test_today_uses_shanghai_date_across_utc_midnight(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 23, 16, 30, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(schedule_service, "datetime", FixedDateTime)
    assert schedule_service.shanghai_today() == date(2026, 10, 24)
