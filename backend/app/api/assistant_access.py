"""Owner consent and administrator pilot membership, using campus identity."""
from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.assistant import assistant_db, assistant_settings, private_response
from app.assistant import access
from app.assistant.schemas import StrictRequest, RequestKey
from app.common.response import Response
from app.dependencies.auth import get_current_admin, get_current_user
from app.models.user import User

router = APIRouter(dependencies=[Depends(private_response)])


class ConsentRequest(StrictRequest):
    policy_version: RequestKey


class EligibilityRequest(StrictRequest):
    eligible: bool
    expected_generation: int = Field(ge=0)


@router.get('/assistant/access')
async def get_access(request: Request, actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    return Response.success(data=await access.state(db, actor.id, assistant_settings(request)))


@router.post('/assistant/consent')
async def confirm(data: ConsentRequest, request: Request, actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    await access.consent(db, actor, data.policy_version)
    return Response.success(data=await access.state(db, actor.id, assistant_settings(request)))


@router.delete('/assistant/consent')
async def withdraw(request: Request, actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    await access.withdraw(db, actor)
    return Response.success(data=await access.state(db, actor.id, assistant_settings(request)))


@router.get('/admin/assistant/access')
async def list_access(page: Annotated[int, Query(ge=1, le=1000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        actor: User = Depends(get_current_admin), db: AsyncSession = Depends(assistant_db)):
    return Response.success(data=await access.list_access(db, page=page, page_size=page_size))


@router.put('/admin/assistant/access/{user_id}')
async def set_access(user_id: Annotated[int, Path(ge=1)], data: EligibilityRequest,
        actor: User = Depends(get_current_admin), db: AsyncSession = Depends(assistant_db)):
    return Response.success(data=await access.set_eligibility(db, user_id, data.eligible, data.expected_generation, actor=actor))
