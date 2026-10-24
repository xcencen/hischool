"""Only explicitly migrated async business routes are mounted."""

from fastapi import APIRouter

from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.user import router as user_router

api = APIRouter(prefix="/api")
api.include_router(auth_router)
api.include_router(user_router)
api.include_router(admin_users_router)
