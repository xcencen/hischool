from fastapi import APIRouter

from app.api.content_management import management_router
from app.schemas.community import ActivityCreate, ActivityUpdate, NoticeCreate, NoticeUpdate
from app.services import activity_service, notice_service

router = APIRouter()
router.include_router(management_router("notices", notice_service, NoticeCreate, NoticeUpdate, own_only=True))
router.include_router(management_router("activities", activity_service, ActivityCreate, ActivityUpdate, own_only=True))
