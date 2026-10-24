"""Only explicitly migrated async business routes are mounted."""

from fastapi import APIRouter

from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.user import router as user_router
from app.api.course import router as course_router
from app.api.schedule import router as schedule_router
from app.api.admin_courses import router as admin_courses_router
from app.api.admin_schedules import router as admin_schedules_router

api = APIRouter(prefix="/api")
api.include_router(auth_router)
api.include_router(user_router)
api.include_router(admin_users_router)
api.include_router(course_router)
api.include_router(schedule_router)
api.include_router(admin_courses_router)
api.include_router(admin_schedules_router)
