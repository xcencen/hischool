"""Administrator-only safe assistant operating state; no Docker access."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.assistant import assistant_settings, private_response
from app.assistant.operations import OperationsUnavailable, snapshot
from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.user import User

router = APIRouter(prefix="/admin/assistant", tags=["助手运行状态"],
                   dependencies=[Depends(private_response)])


@router.get("/operations")
async def operations(request: Request, current_user: User = Depends(get_current_admin),
                     db: AsyncSession = Depends(get_db)):
    try:
        data = await snapshot(db, assistant_settings(request))
    except OperationsUnavailable:
        raise BusinessException("助手运行状态暂时不可用", code=503) from None
    return Response.success(data=data)
