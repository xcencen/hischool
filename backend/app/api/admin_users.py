from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.user import User
from app.schemas.user import UserCreateRequest, UserUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/admin/users", tags=["用户管理"])


@router.get("")
async def list_users(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    q: Annotated[str | None, Query(max_length=50)] = None,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return Response.success(data=await user_service.get_user_page_list(db, page, page_size, q))


@router.post("")
async def create_user(
    data: UserCreateRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return Response.success(message="用户已创建", data=await user_service.create_user(db, data, current_user))


@router.patch("/{user_id}")
async def update_user(
    user_id: Annotated[int, Path(ge=1)],
    data: UserUpdateRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return Response.success(message="用户已更新", data=await user_service.update_user(db, user_id, data, current_user))
