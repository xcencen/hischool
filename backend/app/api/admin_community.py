from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.content_management import management_router
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.user import User
from app.schemas.community import ActivityCreate, ActivityUpdate, CategoryCreate, CategoryUpdate, NoticeCreate, NoticeUpdate
from app.services import activity_service, notice_service

router = APIRouter(tags=["校园内容管理"])
router.include_router(management_router("notices", notice_service, NoticeCreate, NoticeUpdate))
router.include_router(management_router("activities", activity_service, ActivityCreate, ActivityUpdate))


@router.get("/admin/notice-categories")
async def categories(actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await notice_service.categories(db, admin=True))


@router.post("/admin/notice-categories")
async def create_category(data: CategoryCreate, actor: User = Depends(get_current_admin),
                          db: AsyncSession = Depends(get_db)):
    return Response.success(data=await notice_service.save_category(db, data, actor))


@router.patch("/admin/notice-categories/{item_id}")
async def update_category(item_id: Annotated[int, Path(ge=1)], data: CategoryUpdate,
                          actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await notice_service.save_category(db, data, actor, item_id))


@router.delete("/admin/notice-categories/{item_id}")
async def delete_category(item_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_admin),
                          db: AsyncSession = Depends(get_db)):
    await notice_service.delete_category(db, item_id, actor)
    return Response.success(message="分类已删除")
