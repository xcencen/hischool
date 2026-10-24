from datetime import date as CalendarDate
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.user import User
from app.schemas.schedule import ScheduleCreateRequest, ScheduleUpdateRequest
from app.services import schedule_service

router = APIRouter(prefix="/admin/schedules", tags=["排课管理"])


@router.get("")
async def list_schedules(course_id: Annotated[int | None, Query(ge=1)] = None,
                         date: Annotated[CalendarDate | None, Query()] = None,
                         actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await schedule_service.list_schedules(db, course_id=course_id, start=date, end=date))


@router.post("")
async def create(data: ScheduleCreateRequest, actor: User = Depends(get_current_admin),
                 db: AsyncSession = Depends(get_db)):
    return Response.success(message="课时已创建", data=await schedule_service.create_schedule(db, data, actor))


@router.patch("/{schedule_id}")
async def update(schedule_id: Annotated[int, Path(ge=1)], data: ScheduleUpdateRequest,
                 actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(message="课时已更新",
                            data=await schedule_service.update_schedule(db, schedule_id, data, actor))


@router.delete("/{schedule_id}")
async def delete(schedule_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_admin),
                 db: AsyncSession = Depends(get_db)):
    await schedule_service.delete_schedule(db, schedule_id, actor)
    return Response.success(message="课时已删除")
