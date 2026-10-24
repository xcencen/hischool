from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import notice_service

router = APIRouter(tags=["校园通知"])


@router.get("/notice-categories")
async def categories(actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await notice_service.categories(db))


@router.get("/notices")
async def notices(page: Annotated[int, Query(ge=1)] = 1,
                  page_size: Annotated[int, Query(ge=1, le=100)] = 10,
                  q: Annotated[str | None, Query(max_length=100)] = None,
                  category_id: Annotated[int | None, Query(ge=1)] = None,
                  actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await notice_service.list_notices(db, page, page_size, q, category_id))


@router.get("/notices/{item_id}")
async def detail(item_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    return Response.success(data=await notice_service.detail(db, item_id))
