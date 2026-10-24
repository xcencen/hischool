from datetime import date as CalendarDate
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import schedule_service

router = APIRouter(prefix="/schedules", tags=["本人课表"])


@router.get("/today")
async def today_schedule(date: Annotated[CalendarDate | None, Query()] = None,
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    day = date or schedule_service.shanghai_today()
    return Response.success(data=await schedule_service.list_schedules(db, user=current_user, start=day, end=day))


@router.get("/week")
async def week_schedule(date: Annotated[CalendarDate | None, Query()] = None,
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    return Response.success(data=await schedule_service.week_schedules(
        db, current_user, date or schedule_service.shanghai_today()))
