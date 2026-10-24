"""Same management routes for admins and owners, with explicit server scopes."""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin, get_current_staff
from app.models.user import User
from app.schemas.community import ReviewRequest


def management_router(kind, service, create_schema, update_schema, *, own_only=False):
    router = APIRouter(prefix=("/owned/" if own_only else "/admin/") + kind,
                       tags=["本人内容" if own_only else "内容管理"])
    authorize = get_current_staff if own_only else get_current_admin
    list_service = service.list_notices if kind == "notices" else service.list_activities

    @router.get("")
    async def listing(page: Annotated[int, Query(ge=1)] = 1,
                      page_size: Annotated[int, Query(ge=1, le=100)] = 10,
                      q: Annotated[str | None, Query(max_length=100)] = None,
                      actor: User = Depends(authorize), db: AsyncSession = Depends(get_db)):
        return Response.success(data=await list_service(db, page, page_size, q, actor=actor, own_only=own_only))

    @router.get("/{item_id}")
    async def detail(item_id: Annotated[int, Path(ge=1)], actor: User = Depends(authorize),
                     db: AsyncSession = Depends(get_db)):
        return Response.success(data=await service.detail(db, item_id, actor=actor, own_only=own_only))

    @router.post("")
    async def create(data: create_schema, actor: User = Depends(authorize), db: AsyncSession = Depends(get_db)):
        return Response.success(message="内容已保存", data=await service.create(db, data, actor))

    @router.patch("/{item_id}")
    async def update(item_id: Annotated[int, Path(ge=1)], data: update_schema,
                     actor: User = Depends(authorize), db: AsyncSession = Depends(get_db)):
        return Response.success(message="内容已保存",
                                data=await service.update(db, item_id, data, actor, own_only=own_only))

    @router.delete("/{item_id}")
    async def remove(item_id: Annotated[int, Path(ge=1)], actor: User = Depends(authorize),
                     db: AsyncSession = Depends(get_db)):
        await service.remove(db, item_id, actor, own_only=own_only)
        return Response.success(message="内容已删除")

    if not own_only:
        @router.post("/{item_id}/review")
        async def review(item_id: Annotated[int, Path(ge=1)], data: ReviewRequest,
                         actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
            return Response.success(message="审核已完成", data=await service.review(db, item_id, data, actor))
    return router
