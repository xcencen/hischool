"""Campus-authenticated conversation, run, quota and in-app alert interfaces."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response as HttpResponse
from fastapi.security import HTTPAuthorizationCredentials
from jwt import InvalidTokenError
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import budget, conversations
from app.assistant.schemas import (ConversationCreate, ConversationUpdate, RunCreate, RunRetry,
                                   alert_response, run_response)
from app.assistant.settings import load_assistant_settings
from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import bearer, get_current_user
from app.models.assistant import AssistantAlert, AssistantUsage, Conversation
from app.models.user import User
from app.utils.jwt import decode_access_token


def private_response(response: HttpResponse):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(prefix="/assistant", tags=["校园助手"], dependencies=[Depends(private_response)])
Page = Annotated[int, Query(ge=1, le=1000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def assistant_settings(request: Request):
    try:
        return getattr(request.app.state, "assistant_settings", None) or load_assistant_settings()
    except (ValueError, TypeError):
        raise BusinessException("助手配置无效，请检查本地配置", code=503) from None


async def assistant_db(db: AsyncSession = Depends(get_db)):
    try:
        yield db
    except (SQLAlchemyError, RedisError):
        await db.rollback()
        raise BusinessException("助手存储暂不可用，请检查迁移与服务状态", code=503) from None


async def public_run(db, actor, row, *, include_usage=False):
    value = run_response(row)
    value["conversation_id"] = await db.scalar(select(Conversation.public_id).where(
        Conversation.id == row.conversation_id, Conversation.owner_id == actor.id))
    if value["conversation_id"] is None:
        raise BusinessException("运行不存在", code=404)
    if include_usage:
        usage = (await db.scalars(select(AssistantUsage).where(AssistantUsage.run_id == row.id)
                                   .order_by(AssistantUsage.id))).all()
        value["usage"] = [dict(kind=item.kind, resource=item.resource, attempt=item.attempt,
            state=item.state, reserved=str(item.reserved), charged=str(item.charged),
            input_tokens=item.input_tokens, output_tokens=item.output_tokens,
            cache_read_tokens=item.cache_read_tokens, usage_unknown=bool(item.usage_unknown),
            price_version=item.price_version, latency_ms=item.latency_ms) for item in usage]
    return value


@router.post("/conversations", status_code=201)
async def create_conversation(data: ConversationCreate, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    row = await conversations.create_conversation(db, actor, assistant_settings(request), title=data.title)
    return Response.success(data=conversations.conversation_response(row))


@router.get("/conversations")
async def list_conversations(request: Request, page: Page = 1, page_size: PageSize = 20,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    return Response.success(data=await conversations.list_conversations(db, actor, assistant_settings(request),
                                                                       page=page, page_size=page_size))


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: UUID, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    assistant_settings(request)
    row = await conversations.get_conversation(db, actor, str(conversation_id))
    return Response.success(data=conversations.conversation_response(row))


@router.patch("/conversations/{conversation_id}")
async def update_conversation(conversation_id: UUID, data: ConversationUpdate, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    row = await conversations.update_conversation(db, actor, assistant_settings(request), str(conversation_id),
                                                   **data.model_dump(exclude_unset=True))
    return Response.success(data=conversations.conversation_response(row))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: UUID, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    await conversations.delete_conversation(db, actor, assistant_settings(request), str(conversation_id))
    return Response.success(data={"id": str(conversation_id), "state": "deleted"})


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: UUID, request: Request, page: Page = 1, page_size: PageSize = 20,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    return Response.success(data=await conversations.list_messages(db, actor, assistant_settings(request),
        str(conversation_id), page=page, page_size=page_size))


@router.post("/conversations/{conversation_id}/runs", status_code=202)
async def create_run(conversation_id: UUID, data: RunCreate, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    from app.assistant import runs
    row = await runs.create_run(db, request.app.state.redis, actor, request.state.token_payload,
        str(conversation_id), data.content, data.request_key, assistant_settings(request))
    return Response.success(data=await public_run(db, actor, row))


@router.get("/conversations/{conversation_id}/runs")
async def list_runs(conversation_id: UUID, request: Request, page: Page = 1, page_size: PageSize = 20,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    from app.assistant import runs
    assistant_settings(request)
    value = await runs.list_runs(db, actor, str(conversation_id), page=page, page_size=page_size)
    value["list"] = [await public_run(db, actor, row) for row in value["list"]]
    return Response.success(data=value)


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    from app.assistant import runs
    assistant_settings(request)
    row = await runs.get_run(db, actor, str(run_id))
    return Response.success(data=await public_run(db, actor, row, include_usage=True))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: UUID, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    from app.assistant import runs
    row = await runs.cancel_run(db, request.app.state.redis, actor, str(run_id), assistant_settings(request))
    return Response.success(data=await public_run(db, actor, row))


@router.get("/runs/{run_id}/events")
async def stream_run(run_id: UUID, request: Request,
        after: Annotated[int, Query(ge=0, le=250)] = 0,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    # A yield-based get_current_user/get_db dependency would hold its session
    # for the entire SSE response under the pinned FastAPI version. Decode the
    # same JWT contract here; open_stream checks current identity and ownership
    # with short, independent sessions before and throughout the subscription.
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise BusinessException("请先登录", code=401)
    try:
        payload = decode_access_token(credentials.credentials, request.app.state.settings)
    except (InvalidTokenError, ValueError, TypeError):
        raise BusinessException("登录已失效，请重新登录", code=401) from None
    from app.assistant.stream import open_stream
    return await open_stream(request, request.app.state.database, request.app.state.redis,
        assistant_settings(request), str(run_id), dict(payload), after=after)


@router.post("/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: UUID, data: RunRetry, request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    from app.assistant import runs
    row = await runs.retry_run(db, request.app.state.redis, actor, request.state.token_payload,
                               str(run_id), data.request_key, assistant_settings(request))
    return Response.success(data=await public_run(db, actor, row))


@router.get("/budget")
async def get_budget(request: Request, actor: User = Depends(get_current_user),
                     db: AsyncSession = Depends(assistant_db)):
    settings = assistant_settings(request)
    day = (datetime.now(UTC) + timedelta(hours=8)).date()
    value = await budget.snapshot(db, actor.id, day, user_daily_limit=settings.user_daily_limit,
        global_daily_limit=settings.global_daily_limit, include_global=actor.role == "admin")
    value["policy"] = dict(enabled=settings.enabled, allow_campus_data=settings.allow_campus_data,
        run_cost_limit=str(settings.run_cost_limit), alert_ratio=str(settings.alert_ratio),
        retention_days=settings.retention_days)
    return Response.success(data=value)


def alert_scope(actor):
    own = AssistantAlert.owner_id == actor.id
    return or_(own, AssistantAlert.owner_id.is_(None)) if actor.role == "admin" else own


@router.get("/alerts")
async def list_alerts(request: Request, page: Page = 1, page_size: PageSize = 20,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    assistant_settings(request)
    query = select(AssistantAlert).where(alert_scope(actor))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(AssistantAlert.id.desc())
        .offset((page-1)*page_size).limit(page_size))).all()
    return Response.success(data=dict(list=[alert_response(row) for row in rows], total=total or 0,
                                     page=page, page_size=page_size))


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: Annotated[int, Path(ge=1)], request: Request,
        actor: User = Depends(get_current_user), db: AsyncSession = Depends(assistant_db)):
    assistant_settings(request)
    await conversations.lock_control(db, actor)
    row = await db.scalar(select(AssistantAlert).where(AssistantAlert.id == alert_id, alert_scope(actor))
                          .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise BusinessException("告警不存在", code=404)
    row.acknowledged = True
    await db.commit()
    await db.refresh(row)
    return Response.success(data=alert_response(row))
