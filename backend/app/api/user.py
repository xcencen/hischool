from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.user import PasswordUpdateRequest, ProfileUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/user", tags=["个人中心"])


@router.get("/me")
async def get_user_info(current_user: User = Depends(get_current_user)):
    return Response.success(data=user_service.get_user_info(current_user))


@router.patch("/me")
async def update_user_info(
    data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return Response.success(message="资料已更新", data=await user_service.update_user_info(db, current_user, data))


@router.post("/me/password")
async def update_password(
    data: PasswordUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await user_service.update_password(db, current_user, data)
    return Response.success(message="密码已修改，请重新登录")
