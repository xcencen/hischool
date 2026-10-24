from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.schemas.community import ActivityCreate, ActivityUpdate, CategoryCreate, NoticeCreate, NoticeUpdate, ReviewRequest


def test_business_services_reject_non_staff_management_scope_without_database():
    from types import SimpleNamespace
    from app.common.exceptions import BusinessException
    from app.services.publication_service import check_management_scope
    for role, own in [("student", True), ("student", False), ("teacher", False)]:
        with pytest.raises(BusinessException) as error:
            check_management_scope(SimpleNamespace(role=role), own)
        assert error.value.code == 403


def activity_payload(**changes):
    return dict(code="TEST-ACT", title="测试活动", content="演示正文", location="测试教室",
                start_time="2030-01-07T14:00:00+08:00", end_time="2030-01-07T16:00:00+08:00",
                registration_deadline="2030-01-06T14:00:00+08:00", capacity=2, **changes)


@pytest.mark.parametrize("field,value", [
    ("title", " "), ("content", ""), ("code", "x"*51), ("category_id", 0),
    ("owner_id", 2), ("state", "rejected"),
])
def test_notice_validation_and_identity_is_server_owned(field, value):
    payload = dict(code="TEST", title="测试通知", content="正文", category_id=1)
    payload[field] = value
    with pytest.raises(ValidationError):
        NoticeCreate.model_validate(payload)


@pytest.mark.parametrize("changes", [
    {"capacity": 0}, {"capacity": True}, {"location": " "},
    {"start_time": "2030-01-07T14:00:00"},
    {"end_time": "2030-01-07T14:00:00+08:00"},
    {"registration_deadline": "2030-01-08T00:00:00Z"},
    {"enrolled_count": 100}, {"user_id": 100},
])
def test_activity_rejects_invalid_capacity_times_and_server_fields(changes):
    payload = activity_payload()
    payload.update(changes)
    with pytest.raises(ValidationError):
        ActivityCreate.model_validate(payload)


def test_activity_input_converts_shanghai_to_aware_utc():
    data = ActivityCreate.model_validate(activity_payload())
    assert data.start_time == datetime(2030, 1, 7, 6, tzinfo=UTC)


@pytest.mark.parametrize("schema,payload", [
    (NoticeUpdate, {"title": None}), (NoticeUpdate, {"category_id": None}),
    (ActivityUpdate, {"capacity": None}), (ActivityUpdate, {"start_time": "2030-01-07T10:00:00"}),
    (CategoryCreate, {"code": "general", "name": " ", "status": 1}),
])
def test_partial_updates_and_categories_reject_invalid_fields(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_review_requires_exact_positive_revision_and_rejection_reason():
    for payload in (dict(expected_revision=0, action="publish"),
                    dict(expected_revision=1, action="reject", note=" ")):
        with pytest.raises(ValidationError):
            ReviewRequest.model_validate(payload)
