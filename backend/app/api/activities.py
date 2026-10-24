from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import activity_service

router = APIRouter(tags=["校园活动"])


@router.get("/activities")
async def activities(page: Annotated[int, Query(ge=1)] = 1,
                     page_size: Annotated[int, Query(ge=1, le=100)] = 10,
                     q: Annotated[str | None, Query(max_length=100)] = None,
                     actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await activity_service.list_activities(db, page, page_size, q))


@router.get("/activities/{item_id}")
async def detail(item_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    return Response.success(data=await activity_service.detail(db, item_id, viewer=actor))


@router.post("/activities/{item_id}/registrations")
async def register(item_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    return Response.success(message="报名成功", data=await activity_service.register(db, item_id, actor))


@router.post("/activities/{item_id}/registrations/cancel")
async def cancel(item_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    return Response.success(message="已取消报名", data=await activity_service.cancel(db, item_id, actor))


@router.get("/user/me/registrations")
async def my_registrations(page: Annotated[int, Query(ge=1)] = 1,
                           page_size: Annotated[int, Query(ge=1, le=100)] = 10,
                           actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await activity_service.my_registrations(db, actor, page, page_size))
