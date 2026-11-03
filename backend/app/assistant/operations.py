"""Read-only, bounded operator aggregates. Never select content or identities."""
import asyncio
from datetime import timedelta
import json

from sqlalchemy import case, func, or_, select

from app.database import utc_now
from app.models.assistant import AssistantMessage, AssistantRun, AssistantUsage, Conversation

DEADLINE_S = 10
WARNING_AFTER_S = 60
TERMINAL = ("succeeded", "failed", "cancelled", "expired")
SAFE_REASONS = frozenset({"interrupted", "queue_expired", "usage_unknown", "pricing_missing",
    "unauthenticated", "forbidden", "unavailable", "rate_limited", "timeout", "cancelled",
    "expired", "limit", "budget_exceeded", "access_revoked", "consent_required"})


class OperationsUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Assistant operations unavailable")


def _age(now, instant):
    return None if instant is None else max(0, (now-instant).total_seconds())


async def snapshot(db, settings, *, now=None):
    """All counts are durable DB state, not Redis transport queue estimates."""
    try:
        async with asyncio.timeout(DEADLINE_S):
            return await _snapshot(db, settings, now or utc_now())
    except Exception:
        raise OperationsUnavailable() from None


async def _snapshot(db, settings, now):
    async def metric(table, predicate, timestamp):
        count, oldest = (await db.execute(select(func.count(), func.min(timestamp))
            .select_from(table).where(predicate))).one()
        return {"count": count, "oldest_age_s": _age(now, oldest)}

    queue = await metric(AssistantRun, AssistantRun.status == "queued", AssistantRun.create_time)
    overdue = await metric(AssistantRun, (AssistantRun.status == "queued") &
        (AssistantRun.deadline_at <= now), AssistantRun.deadline_at)
    queue.update(overdue_count=overdue["count"], oldest_overdue_s=overdue["oldest_age_s"])
    leases = await metric(AssistantRun, (AssistantRun.status == "running") &
        (AssistantRun.lease_until <= now), AssistantRun.lease_until)
    pending_usage = select(AssistantUsage.id).where(AssistantUsage.run_id == AssistantRun.id,
        AssistantUsage.state == "reserved").exists()
    terminal = await metric(AssistantRun, AssistantRun.status.in_(TERMINAL) &
        or_(AssistantRun.reserved > 0, pending_usage),
        func.coalesce(AssistantRun.finished_at, AssistantRun.update_time))
    reason = case((AssistantRun.reason.in_(SAFE_REASONS), AssistantRun.reason), else_="other")
    reasons = (await db.execute(select(reason.label("reason"), func.count().label("count"))
        .where(AssistantRun.status.in_(("failed", "expired"))).group_by(reason).order_by(reason))).all()

    async def cost(kind):
        count, charged = (await db.execute(select(func.count(), func.coalesce(func.sum(AssistantUsage.charged), 0))
            .where(AssistantUsage.kind == kind,
                   or_(AssistantUsage.state == "unknown", AssistantUsage.usage_unknown.is_(True))))).one()
        return count, format(charged, ".8f")

    model_count, model_charged = await cost("model")
    embedding_count, embedding_charged = await cost("embedding")
    retention = timedelta(days=settings.retention_days)
    old_body = AssistantMessage.create_time < now-retention
    expired_conversation = (Conversation.expires_at <= now) & or_(
        Conversation.state.in_(("deleted", "expired")), Conversation.active_run_id.is_(None))
    count, oldest_body, oldest_expiry = (await db.execute(select(func.count(),
        func.min(case((old_body, AssistantMessage.create_time))),
        func.min(case((expired_conversation, Conversation.expires_at))))
        .select_from(AssistantMessage).join(Conversation, Conversation.id == AssistantMessage.conversation_id)
        .where(AssistantMessage.content.is_not(None), or_(old_body, expired_conversation)))).one()
    cleanup_due = [value for value in (
        oldest_body+retention if oldest_body is not None else None, oldest_expiry) if value is not None]
    cleanup = {"count": count, "oldest_age_s": _age(now, min(cleanup_due) if cleanup_due else None)}
    warnings = []
    for code, age in (("queued_overdue", overdue["oldest_age_s"]),
        ("expired_leases", leases["oldest_age_s"]), ("terminal_reserved", terminal["oldest_age_s"]),
        ("cleanup_overdue", cleanup["oldest_age_s"])):
        if age is not None and age > WARNING_AFTER_S:
            warnings.append(code)
    if model_count:
        warnings.append("model_usage_unknown")
    return {"checked_at": now.isoformat()+"Z", "status": "warning" if warnings else "ok",
        "warning_after_s": WARNING_AFTER_S, "warnings": warnings, "queued": queue,
        "expired_leases": leases, "terminal_reserved": terminal,
        "failed_reasons": [dict(row._mapping) for row in reasons],
        "costs": {"currency": "CNY", "model_unknown_count": model_count,
            "model_unknown_charged": model_charged, "embedding_conservative_count": embedding_count,
            "embedding_conservative_charged": embedding_charged}, "cleanup": cleanup}


async def local_snapshot():
    from app.assistant.settings import load_assistant_settings
    from app.config import load_settings
    from app.database import Database

    database = Database(load_settings().database_url)
    try:
        async with database.session_factory() as db:
            return await snapshot(db, load_assistant_settings())
    finally:
        await database.dispose()


def main():
    try:
        result = asyncio.run(local_snapshot())
    except Exception:
        print(json.dumps({"status": "unavailable"}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] == "warning" else 0


if __name__ == "__main__":
    raise SystemExit(main())
