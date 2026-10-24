from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["注册登录"])


@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = await auth_service.register(db, data)
    return Response.success(message="注册成功", data=user)


@router.post("/login")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    return Response.success(message="登录成功", data=await auth_service.login(db, data, request))


@router.post("/logout")
async def logout(request: Request, current_user: User = Depends(get_current_user)):
    await auth_service.logout(request)
    return Response.success(message="已退出登录")
