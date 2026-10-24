from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.knowledge.settings import load_knowledge_settings
from app.models.user import User
from app.schemas.knowledge import KnowledgeSearchRequest
from app.services import knowledge_service

router = APIRouter(prefix="/knowledge", tags=["校园知识检索"])


def knowledge_settings():
    try:
        return load_knowledge_settings()
    except (ValueError, TypeError):
        raise BusinessException("知识库配置无效，请检查本地配置", code=503) from None


@router.get("/status")
async def status(actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await knowledge_service.status(db, knowledge_settings()))


@router.get("/documents")
async def documents(actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response.success(data=await knowledge_service.documents(db))


@router.post("/search")
async def search(data: KnowledgeSearchRequest, actor: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    return Response.success(data=await knowledge_service.search(db, knowledge_settings(), data.query, data.top_k))


@router.get("/documents/{document_id}/source")
async def source(document_id: Annotated[int, Path(ge=1)], version: Annotated[int, Query(ge=1)],
                 actor: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    path, mime, name = await knowledge_service.source(db, knowledge_settings(), document_id, version)
    return FileResponse(path, media_type=mime, filename=name, content_disposition_type="inline",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
