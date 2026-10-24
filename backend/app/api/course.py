from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import course_service

router = APIRouter(prefix="/courses", tags=["校园课程"])


@router.get("")
async def list_courses(q: Annotated[str | None, Query(max_length=100)] = None,
                       current_user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    return Response.success(data=await course_service.list_courses(db, q))


@router.get("/{course_id}")
async def course_detail(course_id: Annotated[int, Path(ge=1)],
                        current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    return Response.success(data=await course_service.get_course(db, course_id))
