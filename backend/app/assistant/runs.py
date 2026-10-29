"""Durable run admission and fenced execution state, independent of model SDKs."""

import asyncio
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import func, select

from app.assistant import budget, conversations
from app.common.exceptions import BusinessException
from app.database import utc_now
from app.infra.redis import RedisUnavailable, rate_limit
from app.models.assistant import AssistantControl, AssistantMessage, AssistantRun, Conversation
from app.services.identity_service import active_identity


TERMINAL = frozenset({"succeeded", "failed", "cancelled", "expired"})
SHANGHAI = timezone(timedelta(hours=8))


class RunStopped(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("Assistant run stopped")


def bounded_sql(function):
    @wraps(function)
    async def bounded(*args, **kwargs):
        async with asyncio.timeout(10):
            return await function(*args, **kwargs)
    return bounded


def budget_day():
    return datetime.now(SHANGHAI).date()


def require_enabled(settings):
    if not settings.enabled or not settings.allow_campus_data:
        raise BusinessException("助手运行尚未启用，请先确认数据使用范围与本地配置", code=503)


async def get_run(db, actor, run_public_id):
    row = await db.scalar(select(AssistantRun).join(Conversation, Conversation.id == AssistantRun.conversation_id)
        .where(AssistantRun.public_id == run_public_id, AssistantRun.owner_id == actor.id,
               Conversation.owner_id == actor.id, Conversation.state != "deleted"))
    if row is None:
        raise BusinessException("运行不存在", code=404)
    return row


async def list_runs(db, actor, conversation_public_id, *, page=1, page_size=20):
    conversation = await conversations.get_conversation(db, actor, conversation_public_id)
    if not 1 <= page <= 1000 or not 1 <= page_size <= 100:
        raise BusinessException("分页参数无效", code=422)
    query = select(AssistantRun).where(AssistantRun.conversation_id == conversation.id,
                                     AssistantRun.owner_id == actor.id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list((await db.scalars(query.order_by(AssistantRun.id.desc())
        .offset((page - 1) * page_size).limit(page_size))).all())
    return dict(list=rows, total=total or 0, page=page, page_size=page_size)


async def create_run(db, redis, actor, token_payload, conversation_public_id, content, request_key,
                     settings, parent_public_id=None):
    require_enabled(settings)
    if (type(content) is not str or not 1 <= len(content.strip()) <= 4000
            or type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_key)):
        raise BusinessException("运行参数无效", code=422)
    content = content.strip()
    if (str(actor.id) != token_payload.get("sub") or actor.auth_version != token_payload.get("auth_version")
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token_payload.get("jti", ""))):
        raise BusinessException("登录已失效，请重新登录", code=401)
    await conversations.lock_control(db, actor)
    await active_identity(db, redis, user_id=actor.id, auth_version=token_payload["auth_version"],
        session_jti=token_payload["jti"], expires_at=token_payload["exp"], current_read=True)
    conversation = await conversations.get_conversation(db, actor, conversation_public_id, for_update=True)
    digest = hashlib.sha256(json.dumps([content, parent_public_id], ensure_ascii=False).encode()).hexdigest()
    existing = await db.scalar(select(AssistantRun).where(AssistantRun.conversation_id == conversation.id,
        AssistantRun.request_key == request_key).with_for_update())
    if existing:
        if existing.request_hash != digest:
            raise BusinessException("幂等键已用于不同请求", code=409)
        await db.commit()
        return existing
    now = utc_now()
    if conversation.state != "active" or conversation.expires_at <= now:
        raise BusinessException("会话已归档或过期", code=409)
    if conversation.active_run_id is not None:
        raise BusinessException("该会话已有运行，请等待完成或取消", code=409)
    pending = list((await db.scalars(select(AssistantRun).where(
        AssistantRun.status.in_(["queued", "running"])).with_for_update())).all())
    if len(pending) >= 100 or sum(row.owner_id == actor.id for row in pending) >= 10:
        raise BusinessException("运行队列已满，请稍后重试", code=429)
    try:
        allowed = await rate_limit(f"assistant:submit:{actor.id}", capacity=10, refill_per_s=1 / 6, client=redis)
    except RedisUnavailable:
        raise BusinessException("运行调度服务暂不可用", code=503) from None
    if not allowed:
        raise BusinessException("提交过于频繁，请稍后重试", code=429)
    parent_id = None
    if parent_public_id:
        parent = await db.scalar(select(AssistantRun).where(AssistantRun.public_id == parent_public_id,
            AssistantRun.conversation_id == conversation.id, AssistantRun.owner_id == actor.id).with_for_update())
        if parent is None or parent.status not in {"failed", "cancelled", "expired"}:
            raise BusinessException("仅可重新提交本人已终止的失败运行", code=409)
        parent_id = parent.id
    row = AssistantRun(public_id=str(uuid4()), conversation_id=conversation.id, owner_id=actor.id,
        request_key=request_key, request_hash=digest, parent_id=parent_id, status="queued",
        source_jti=token_payload["jti"], source_exp=token_payload["exp"], auth_version=token_payload["auth_version"],
        available_at=now, deadline_at=now + timedelta(seconds=settings.queue_timeout_s),
        cost_limit=settings.run_cost_limit, budget_day=budget_day(), reserved=0, spent=0,
        model_calls=0, tool_calls=0, cancel_requested=False)
    db.add(row)
    await db.flush()
    db.add(AssistantMessage(conversation_id=conversation.id, run_id=row.id, sequence=conversation.next_seq,
        role="user", content=content, citations=[]))
    conversation.next_seq += 1
    conversation.expires_at = now + timedelta(days=settings.retention_days)
    if await budget.reserve_run(db, row, user_daily_limit=settings.user_daily_limit,
            global_daily_limit=settings.global_daily_limit, alert_ratio=settings.alert_ratio):
        conversation.active_run_id = row.public_id
    else:
        row.status, row.reason, row.finished_at = "failed", "budget_exceeded", now
        row.source_jti = row.source_exp = None
    await db.commit()
    return row


async def retry_run(db, redis, actor, token_payload, run_public_id, request_key, settings):
    parent = await get_run(db, actor, run_public_id)
    conversation = await db.get(Conversation, parent.conversation_id)
    message = await db.scalar(select(AssistantMessage).where(AssistantMessage.run_id == parent.id,
                                                            AssistantMessage.role == "user"))
    if message is None or not message.content or message.create_time < utc_now() - timedelta(days=settings.retention_days):
        raise BusinessException("运行正文已过期，请重新输入问题", code=410)
    return await create_run(db, redis, actor, token_payload, conversation.public_id, message.content,
                            request_key, settings, parent_public_id=parent.public_id)


async def cancel_run(db, redis, actor, run_public_id, settings):
    await conversations.lock_control(db, actor)
    row = await get_run(db, actor, run_public_id)
    conversation = await db.scalar(select(Conversation).where(Conversation.id == row.conversation_id).with_for_update())
    row = await db.scalar(select(AssistantRun).where(AssistantRun.id == row.id)
        .with_for_update().execution_options(populate_existing=True))
    if row.status not in TERMINAL:
        row.cancel_requested = True
        if row.status == "queued":
            await _finish(db, row, conversation, "cancelled", "cancelled")
    await db.commit()
    return row


async def _control(db):
    if await db.scalar(select(AssistantControl).where(AssistantControl.id == 1).with_for_update()) is None:
        raise RunStopped("configuration")


async def _locked(db, public_id):
    await _control(db)
    row = await db.scalar(select(AssistantRun).where(AssistantRun.public_id == public_id))
    if row is None:
        raise RunStopped("not_found")
    conversation = await db.scalar(select(Conversation).where(Conversation.id == row.conversation_id).with_for_update())
    row = await db.scalar(select(AssistantRun).where(AssistantRun.id == row.id)
        .with_for_update().execution_options(populate_existing=True))
    return row, conversation


def check_lease(row, lease_token):
    if (row.status != "running" or row.lease_token != lease_token or row.lease_until is None
            or row.lease_until <= utc_now()):
        raise RunStopped("lease_lost")
    if row.cancel_requested:
        raise RunStopped("cancelled")
    if row.deadline_at <= utc_now():
        raise RunStopped("timeout")


@bounded_sql
async def claim_next(database, redis, settings):
    require_enabled(settings)
    async with database.session_factory() as db:
        await _control(db)
        now = utc_now()
        active = list((await db.scalars(select(AssistantRun).where(AssistantRun.status == "running")
            .with_for_update())).all())
        if len(active) >= settings.global_concurrency:
            await db.commit()
            return None
        blocked = {row.owner_id for row in active if sum(item.owner_id == row.owner_id for item in active) >= settings.user_concurrency}
        query = select(AssistantRun).where(AssistantRun.status == "queued", AssistantRun.available_at <= now)
        if blocked:
            query = query.where(AssistantRun.owner_id.not_in(blocked))
        row = await db.scalar(query.order_by(AssistantRun.id).limit(1).with_for_update(skip_locked=True))
        if row is None:
            await db.commit()
            return None
        conversation = await db.scalar(select(Conversation).where(Conversation.id == row.conversation_id).with_for_update())
        reason = None
        if row.deadline_at <= now or row.budget_day != budget_day():
            reason = "queue_expired"
        elif row.cancel_requested or conversation.state != "active" or conversation.expires_at <= now:
            reason = "cancelled"
        else:
            try:
                await active_identity(db, redis, user_id=row.owner_id, auth_version=row.auth_version,
                    session_jti=row.source_jti, expires_at=row.source_exp, current_read=True)
            except BusinessException as error:
                reason = "unauthenticated" if error.code == 401 else "unavailable"
        if reason:
            await _finish(db, row, conversation, "expired" if reason == "queue_expired" else "failed", reason)
            await db.commit()
            return None
        row.status, row.started_at = "running", now
        row.lease_token, row.lease_until = uuid4().hex, now + timedelta(seconds=settings.lease_s)
        row.deadline_at = now + timedelta(seconds=settings.run_timeout_s)
        await db.commit()
        return row


@bounded_sql
async def guard(database, redis, public_id, lease_token, settings):
    async with database.session_factory() as db:
        row, conversation = await _locked(db, public_id)
        check_lease(row, lease_token)
        if conversation.state != "active" or conversation.active_run_id != public_id or conversation.expires_at <= utc_now():
            raise RunStopped("cancelled")
        try:
            await active_identity(db, redis, user_id=row.owner_id, auth_version=row.auth_version,
                session_jti=row.source_jti, expires_at=row.source_exp, current_read=True)
        except BusinessException as error:
            raise RunStopped("unauthenticated" if error.code == 401 else "unavailable") from None
        row.lease_until = utc_now() + timedelta(seconds=settings.lease_s)
        await db.commit()


async def _finish(db, row, conversation, status, reason=None, *, text=None, citations=None):
    await budget.release_run(db, row)
    if status == "succeeded":
        if not isinstance(text, str) or not text.strip() or len(text) > 16000:
            raise RunStopped("invalid_response")
        db.add(AssistantMessage(conversation_id=row.conversation_id, run_id=row.id,
            sequence=conversation.next_seq, role="assistant", content=text, citations=citations or []))
        conversation.next_seq += 1
    row.status, row.reason, row.finished_at = status, reason, utc_now()
    row.lease_token = row.lease_until = row.source_jti = row.source_exp = None
    if conversation.active_run_id == row.public_id:
        conversation.active_run_id = None


@bounded_sql
async def finish(database, public_id, lease_token, *, status, reason=None, text=None, citations=None, redis=None):
    if status not in TERMINAL:
        raise ValueError("Invalid final run state")
    async with database.session_factory() as db:
        row, conversation = await _locked(db, public_id)
        if row.status in TERMINAL:
            await db.commit()
            return
        if row.lease_token != lease_token or row.lease_until <= utc_now():
            raise RunStopped("lease_lost")
        if row.cancel_requested and status == "succeeded":
            status, reason, text, citations = "cancelled", "cancelled", None, None
        if status == "succeeded":
            if redis is None:
                raise RunStopped("configuration")
            if (row.deadline_at <= utc_now() or conversation.state != "active"
                    or conversation.expires_at <= utc_now()):
                status, reason, text, citations = "failed", "timeout", None, None
            else:
                try:
                    await active_identity(db, redis, user_id=row.owner_id, auth_version=row.auth_version,
                        session_jti=row.source_jti, expires_at=row.source_exp, current_read=True)
                except BusinessException as error:
                    status = "failed"
                    reason = "unauthenticated" if error.code == 401 else "unavailable"
                    text = citations = None
        await _finish(db, row, conversation, status, reason, text=text, citations=citations)
        await db.commit()


@bounded_sql
async def recover_abandoned(database, *, limit=100):
    """Release dead runs conservatively; never replay an in-flight paid request."""
    recovered = 0
    async with database.session_factory() as db:
        await _control(db)
        now = utc_now()
        rows = list((await db.scalars(select(AssistantRun).where(
            ((AssistantRun.status == "running") & (AssistantRun.lease_until <= now)) |
            ((AssistantRun.status == "queued") & (AssistantRun.deadline_at <= now)))
            .order_by(AssistantRun.id).limit(limit).with_for_update(skip_locked=True))).all())
        for row in rows:
            conversation = await db.scalar(select(Conversation).where(Conversation.id == row.conversation_id).with_for_update())
            await _finish(db, row, conversation, "failed" if row.status == "running" else "expired",
                          "interrupted" if row.status == "running" else "queue_expired")
            recovered += 1
        await db.commit()
    return recovered
