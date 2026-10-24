"""Only explicitly migrated async business routes are mounted."""

from fastapi import APIRouter

from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.user import router as user_router
from app.api.course import router as course_router
from app.api.schedule import router as schedule_router
from app.api.admin_courses import router as admin_courses_router
from app.api.admin_schedules import router as admin_schedules_router
from app.api.notices import router as notices_router
from app.api.activities import router as activities_router
from app.api.admin_community import router as admin_community_router
from app.api.owned_content import router as owned_content_router
from app.api.knowledge import router as knowledge_router

api = APIRouter(prefix="/api")
api.include_router(auth_router)
api.include_router(user_router)
api.include_router(admin_users_router)
api.include_router(course_router)
api.include_router(schedule_router)
api.include_router(admin_courses_router)
api.include_router(admin_schedules_router)
api.include_router(notices_router)
api.include_router(activities_router)
api.include_router(admin_community_router)
api.include_router(owned_content_router)
api.include_router(knowledge_router)
