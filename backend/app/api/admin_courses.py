from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.user import User
from app.schemas.course import CourseCreateRequest, CourseStudentsRequest, CourseUpdateRequest
from app.services import course_service

router = APIRouter(prefix="/admin/courses", tags=["课程管理"])


@router.get("")
async def list_courses(q: Annotated[str | None, Query(max_length=100)] = None,
                       actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await course_service.list_courses(db, q, admin=True))


@router.get("/options")
async def options(actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await course_service.course_options(db))


@router.post("")
async def create(data: CourseCreateRequest, actor: User = Depends(get_current_admin),
                 db: AsyncSession = Depends(get_db)):
    return Response.success(message="课程已创建", data=await course_service.create_course(db, data, actor))


@router.patch("/{course_id}")
async def update(course_id: Annotated[int, Path(ge=1)], data: CourseUpdateRequest,
                 actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(message="课程已更新", data=await course_service.update_course(db, course_id, data, actor))


@router.delete("/{course_id}")
async def delete(course_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_admin),
                 db: AsyncSession = Depends(get_db)):
    await course_service.delete_course(db, course_id, actor)
    return Response.success(message="课程已删除")


@router.get("/{course_id}/students")
async def students(course_id: Annotated[int, Path(ge=1)], actor: User = Depends(get_current_admin),
                   db: AsyncSession = Depends(get_db)):
    return Response.success(data=await course_service.course_students(db, course_id))


@router.put("/{course_id}/students")
async def replace_students(course_id: Annotated[int, Path(ge=1)], data: CourseStudentsRequest,
                           actor: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return Response.success(message="选课名单已保存",
        data=await course_service.replace_students(db, course_id, data.student_ids, actor))
