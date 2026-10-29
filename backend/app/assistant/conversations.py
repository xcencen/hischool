"""Owner-scoped conversation state and bounded, successful-turn context."""

from collections import defaultdict
from datetime import timedelta
import json
from uuid import uuid4

from sqlalchemy import func, or_, select, update

from app.common.exceptions import BusinessException
from app.database import utc_now
from app.models.assistant import AssistantControl, AssistantMessage, AssistantRun, Conversation
from app.models.user import User
from app.assistant.schemas import timestamp


async def lock_control(db, actor=None):
    """Serialize short assistant mutations; network work never holds this lock."""
    control = await db.scalar(select(AssistantControl).where(AssistantControl.id == 1).with_for_update())
    if control is None:
        raise BusinessException("助手数据结构尚未初始化", code=503)
    if actor is not None:
        expected_version, user_id = actor.auth_version, actor.id
        current = await db.scalar(select(User).where(User.id == user_id)
            .with_for_update(read=True).execution_options(populate_existing=True))
        if current is None or current.status != 1 or current.auth_version != expected_version:
            raise BusinessException("登录已失效，请重新登录", code=401)


async def get_conversation(db, actor, public_id, *, for_update=False):
    query = select(Conversation).where(Conversation.public_id == public_id,
        Conversation.owner_id == actor.id, Conversation.state != "deleted")
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise BusinessException("会话不存在", code=404)
    return row


def conversation_response(row, *, now=None):
    now = now or utc_now()
    expired = row.expires_at <= now or row.state == "expired"
    return dict(id=row.public_id, title="已过期会话" if expired else row.title,
        state="expired" if expired else row.state, active_run_id=row.active_run_id,
        created_at=timestamp(row.create_time), updated_at=timestamp(row.update_time),
        expires_at=timestamp(row.expires_at))


async def create_conversation(db, actor, settings, *, title="新会话"):
    await lock_control(db, actor)
    row = Conversation(public_id=str(uuid4()), owner_id=actor.id, title=title,
        state="active", next_seq=1, active_run_id=None,
        expires_at=utc_now() + timedelta(days=settings.retention_days))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_conversations(db, actor, settings, *, page=1, page_size=20):
    query = select(Conversation).where(Conversation.owner_id == actor.id, Conversation.state != "deleted")
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(Conversation.id.desc()).offset((page-1)*page_size)
                             .limit(page_size))).all()
    return dict(list=[conversation_response(row) for row in rows], total=total or 0,
                page=page, page_size=page_size)


async def update_conversation(db, actor, settings, public_id, *, title=None, state=None):
    await lock_control(db, actor)
    row = await get_conversation(db, actor, public_id, for_update=True)
    if row.active_run_id is not None:
        raise BusinessException("请先结束当前运行", code=409)
    if row.state == "expired" or row.expires_at <= utc_now():
        raise BusinessException("会话已过期，请创建新会话", code=410)
    if title is not None:
        row.title = title
    if state is not None:
        row.state = state
    await db.commit()
    await db.refresh(row)
    return row


async def delete_conversation(db, actor, settings, public_id):
    await lock_control(db, actor)
    row = await db.scalar(select(Conversation).where(Conversation.public_id == public_id,
        Conversation.owner_id == actor.id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise BusinessException("会话不存在", code=404)
    if row.active_run_id is not None:
        raise BusinessException("请先结束当前运行", code=409)
    row.state, row.title = "deleted", "已删除会话"
    await db.execute(update(AssistantMessage).where(AssistantMessage.conversation_id == row.id)
                     .values(content=None, citations=[]))
    await db.commit()


async def list_messages(db, actor, settings, public_id, *, page=1, page_size=20):
    conversation = await get_conversation(db, actor, public_id)
    query = (select(AssistantMessage, AssistantRun.public_id)
        .outerjoin(AssistantRun, AssistantRun.id == AssistantMessage.run_id)
        .where(AssistantMessage.conversation_id == conversation.id))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(AssistantMessage.sequence)
        .offset((page-1)*page_size).limit(page_size))).all()
    now = utc_now()
    cutoff = now - timedelta(days=settings.retention_days)
    expired = conversation.expires_at <= now or conversation.state == "expired"
    values = []
    for message, run_id in rows:
        redacted = expired or message.create_time < cutoff or message.content is None
        values.append(dict(id=message.id, sequence=message.sequence, run_id=run_id,
            role=message.role, content=None if redacted else message.content,
            citations=[] if redacted else message.citations, redacted=redacted,
            created_at=timestamp(message.create_time)))
    return dict(list=values, total=total or 0, page=page, page_size=page_size)


def bounded_context(messages, *, turns, max_bytes):
    """Keep complete successful pairs; discard whole oldest turns when full."""
    by_run = defaultdict(list)
    for message in messages:
        by_run[message.run_id].append(message)
    pairs = []
    for rows in by_run.values():
        rows = sorted(rows, key=lambda row: row.sequence)
        if (len(rows) == 2 and rows[0].role == "user" and rows[1].role == "assistant"
                and rows[0].content is not None and rows[1].content is not None):
            pairs.append((rows[0].sequence, [dict(role=row.role, content=row.content) for row in rows]))
    pairs.sort(key=lambda value: value[0])
    selected = [pair for _, pair in pairs[-turns:]]
    while selected:
        flat = [message for pair in selected for message in pair]
        if len(json.dumps(flat, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= max_bytes:
            return flat
        selected.pop(0)
    return []


async def context_messages(db, conversation, settings):
    now = utc_now()
    if (conversation.state in {"deleted", "expired"} or conversation.expires_at <= now):
        return []
    ids = (await db.scalars(select(AssistantRun.id).where(
        AssistantRun.conversation_id == conversation.id, AssistantRun.status == "succeeded")
        .order_by(AssistantRun.id.desc()).limit(settings.context_turns))).all()
    if not ids:
        return []
    messages = (await db.scalars(select(AssistantMessage).where(
        AssistantMessage.conversation_id == conversation.id, AssistantMessage.run_id.in_(ids),
        AssistantMessage.create_time >= now - timedelta(days=settings.retention_days))
        .order_by(AssistantMessage.sequence))).all()
    return bounded_context(messages, turns=settings.context_turns, max_bytes=settings.context_max_bytes)


async def purge_expired(db, settings, *, limit=100):
    """Bounded maintenance transaction; callers repeat it on their worker tick."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Invalid assistant purge limit")
    await lock_control(db)
    now = utc_now()
    conversations = (await db.scalars(select(Conversation).where(
        Conversation.expires_at <= now, Conversation.state.not_in(("deleted", "expired")),
        Conversation.active_run_id.is_(None)).order_by(Conversation.id).limit(limit).with_for_update())).all()
    for row in conversations:
        row.state, row.title = "expired", "已过期会话"
    await db.flush()
    ids = (await db.scalars(select(AssistantMessage.id).where(
        or_(AssistantMessage.create_time < now - timedelta(days=settings.retention_days),
            AssistantMessage.conversation_id.in_(select(Conversation.id).where(
                Conversation.state.in_(("deleted", "expired")), Conversation.expires_at <= now))),
        AssistantMessage.content.is_not(None)).order_by(AssistantMessage.id)
        .limit(limit).with_for_update())).all()
    if ids:
        await db.execute(update(AssistantMessage).where(AssistantMessage.id.in_(ids))
                         .values(content=None, citations=[]))
    await db.commit()
    return dict(expired_conversations=len(conversations), redacted_messages=len(ids))
