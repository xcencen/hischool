"""Transactional Decimal reservations, settlement and deduplicated budget alerts.

The caller owns the transaction and locks the run first. Budget rows are always
locked global -> user; calls are locked only after those rows. No network I/O,
automatic commits, SDK imports or best-effort accounting are used here.
"""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import re

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert

from app.database import utc_now
from app.models.assistant import AssistantAlert, AssistantBudget, AssistantUsage


UNIT = Decimal("0.00000001")
ZERO = Decimal("0.00000000")
MAX_MONEY = Decimal("9999999999.99999999")
ALERT_RATIO = Decimal("0.8")


class BudgetExceeded(RuntimeError):
    reason = "budget_exceeded"

    def __init__(self):
        super().__init__("Assistant budget is exhausted")


def money(value):
    """Round a finite nonnegative decimal upward without accepting binary floats."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Budget amounts must be finite nonnegative decimals")
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result > MAX_MONEY:
            raise ValueError("Invalid budget amount")
        return result.quantize(UNIT, rounding=ROUND_CEILING)
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid budget amount") from None


def _ratio(value):
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite() or not 0 < value <= 1:
        raise ValueError("Invalid budget alert ratio")
    return value


async def _alert(db, *, owner_id, day, scope, scope_id, kind, amount, cap):
    values = dict(owner_id=owner_id, day=day, scope=scope, scope_id=scope_id,
        kind=kind, acknowledged=False, amount=money(amount), cap=money(cap),
        create_time=utc_now(), update_time=utc_now())
    statement = insert(AssistantAlert).values(**values)
    # Acknowledgment belongs to the user. Re-observing the same condition does
    # not re-open it or create an alert on every worker heartbeat.
    await db.execute(statement.on_duplicate_key_update(
        amount=func.greatest(AssistantAlert.amount, statement.inserted.amount),
        cap=func.least(AssistantAlert.cap, statement.inserted.cap), update_time=utc_now()))


async def _create_budget(db, day, scope, scope_id, cap):
    statement = insert(AssistantBudget).values(day=day, scope=scope, scope_id=scope_id,
        cap=money(cap), spent=ZERO, reserved=ZERO, create_time=utc_now(), update_time=utc_now())
    await db.execute(statement.on_duplicate_key_update(id=AssistantBudget.id))
    row = await db.scalar(select(AssistantBudget).where(AssistantBudget.day == day,
        AssistantBudget.scope == scope, AssistantBudget.scope_id == scope_id)
        .with_for_update().execution_options(populate_existing=True))
    # Increasing configuration cannot enlarge an already admitted day's quota.
    # Decreases take effect immediately, even if existing commitments exceed it.
    row.cap = min(row.cap, money(cap))
    await db.flush()
    return row


async def _rows(db, run, *, required=True):
    rows = []
    for scope, scope_id in (("global", 0), ("user", run.owner_id)):
        row = await db.scalar(select(AssistantBudget).where(AssistantBudget.day == run.budget_day,
            AssistantBudget.scope == scope, AssistantBudget.scope_id == scope_id)
            .with_for_update().execution_options(populate_existing=True))
        if row is None:
            if required:
                raise RuntimeError("Assistant budget reservation is unavailable")
            return []
        rows.append(row)
    return rows


async def _daily_alerts(db, rows, *, ratio=ALERT_RATIO, overrun=False):
    ratio = _ratio(ratio) if ratio is not None else None
    for row in rows:
        committed = row.spent + row.reserved
        if ratio is not None and committed >= row.cap * ratio:
            await _alert(db, owner_id=row.scope_id if row.scope == "user" else None,
                day=row.day, scope=row.scope, scope_id=row.scope_id,
                kind="threshold", amount=committed, cap=row.cap)
        if overrun and committed > row.cap:
            await _alert(db, owner_id=row.scope_id if row.scope == "user" else None,
                day=row.day, scope=row.scope, scope_id=row.scope_id,
                kind="overrun", amount=committed, cap=row.cap)


async def reserve_run(db, run, *, user_daily_limit, global_daily_limit, alert_ratio):
    """Reserve the full run cap in both daily buckets or record a denial alert."""
    ratio, amount = _ratio(alert_ratio), money(run.cost_limit)
    if amount == 0 or run.status != "queued":
        raise BudgetExceeded()
    if money(run.reserved or ZERO) + money(run.spent or ZERO) > 0:
        return True
    global_row = await _create_budget(db, run.budget_day, "global", 0, global_daily_limit)
    user_row = await _create_budget(db, run.budget_day, "user", run.owner_id, user_daily_limit)
    rows = [global_row, user_row]
    denied = [row for row in rows if row.spent + row.reserved + amount > row.cap]
    if denied:
        for row in denied:
            await _alert(db, owner_id=row.scope_id if row.scope == "user" else None,
                day=row.day, scope=row.scope, scope_id=row.scope_id, kind="limit",
                amount=row.spent + row.reserved + amount, cap=row.cap)
        await _alert(db, owner_id=run.owner_id, day=run.budget_day, scope="run", scope_id=run.id,
            kind="limit", amount=amount, cap=run.cost_limit)
        return False
    for row in rows:
        row.reserved += amount
    run.reserved = amount
    await _daily_alerts(db, rows, ratio=ratio)
    await db.flush()
    return True


async def start_call(db, run, *, call_key, kind, upper_bound, resource, price_snapshot, attempt=1):
    """Create a call intent before dispatch; an existing intent is never replayed."""
    upper_bound = money(upper_bound)
    if (not isinstance(call_key, str) or not re.fullmatch(r"[!-~]{1,64}", call_key)
            or kind not in {"model", "embedding", "tool"}
            or not isinstance(resource, str) or not 1 <= len(resource) <= 100
            or type(attempt) is not int or attempt < 1 or not isinstance(price_snapshot, dict)):
        raise ValueError("Invalid assistant call intent")
    try:
        snapshot_json = json.dumps(price_snapshot, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("Invalid assistant price snapshot") from None
    if len(snapshot_json.encode("utf-8")) > 4096:
        raise ValueError("Assistant price snapshot is too large")
    await _rows(db, run)
    previous = await db.scalar(select(AssistantUsage.id).where(
        AssistantUsage.run_id == run.id, AssistantUsage.call_key == call_key))
    if previous is not None:
        raise RuntimeError("Assistant call intent already exists")
    pending = await db.scalar(select(func.sum(AssistantUsage.reserved)).where(
        AssistantUsage.run_id == run.id, AssistantUsage.state == "reserved")) or ZERO
    if pending + upper_bound > money(run.reserved):
        await _alert(db, owner_id=run.owner_id, day=run.budget_day, scope="run", scope_id=run.id,
            kind="limit", amount=run.spent + pending + upper_bound, cap=run.cost_limit)
        raise BudgetExceeded()
    usage = AssistantUsage(run_id=run.id, call_key=call_key, kind=kind,
        state="reserved", reserved=upper_bound, charged=ZERO, resource=resource,
        price_snapshot=json.loads(snapshot_json), attempt=attempt, usage_unknown=False)
    db.add(usage)
    await db.flush()
    return usage


def _count(value):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError("Invalid assistant token count")
    return value


async def settle_call(db, run, usage, *, cost, input_tokens=None, output_tokens=None,
                      cache_read_tokens=None, price_version=None, latency_ms=0, unknown=False):
    """Atomically move the charged cost out of reservations; repeated calls are inert."""
    if type(unknown) is not bool or type(latency_ms) is not int or latency_ms < 0:
        raise ValueError("Invalid assistant call settlement")
    counts = [_count(value) for value in (input_tokens, output_tokens, cache_read_tokens)]
    if counts[0] is not None and counts[2] is not None and counts[2] > counts[0]:
        raise ValueError("Cached tokens exceed input tokens")
    if price_version is not None and (not isinstance(price_version, str) or len(price_version) > 100):
        raise ValueError("Invalid assistant price version")
    rows = await _rows(db, run)
    current = await db.scalar(select(AssistantUsage).where(AssistantUsage.id == usage.id,
        AssistantUsage.run_id == run.id).with_for_update().execution_options(populate_existing=True))
    if current is None:
        raise RuntimeError("Assistant call intent is unavailable")
    if current.state != "reserved":
        return current
    charge = current.reserved if unknown else money(cost)
    released = min(money(run.reserved), charge)
    if any(row.reserved < released for row in rows):
        raise RuntimeError("Assistant budget reservation is inconsistent")
    run.reserved = money(run.reserved) - released
    run.spent = money(run.spent) + charge
    for row in rows:
        row.reserved -= released
        row.spent += charge
    current.state = "unknown" if unknown else "settled"
    current.charged, current.usage_unknown = charge, unknown
    current.input_tokens, current.output_tokens, current.cache_read_tokens = ([None] * 3 if unknown else counts)
    current.price_version, current.latency_ms = price_version, latency_ms
    if unknown:
        await _alert(db, owner_id=run.owner_id, day=run.budget_day, scope="run", scope_id=run.id,
            kind="unknown_usage", amount=run.spent, cap=run.cost_limit)
    if charge > current.reserved or run.spent > run.cost_limit:
        await _alert(db, owner_id=run.owner_id, day=run.budget_day, scope="run", scope_id=run.id,
            kind="overrun", amount=run.spent, cap=run.cost_limit)
    # Admission checks the configured threshold against spent + reserved.
    # Normal settlement only transfers between those columns, so it cannot
    # newly cross that threshold. Do not reapply an unrelated default ratio.
    # Charges exceeding their reservation receive the stronger overrun alert.
    await _daily_alerts(db, rows, ratio=None, overrun=True)
    await db.flush()
    return current


async def release_run(db, run):
    """Charge unresolved dispatched intents conservatively, then free unused funds."""
    rows = await _rows(db, run, required=False)
    pending = list((await db.scalars(select(AssistantUsage).where(AssistantUsage.run_id == run.id,
        AssistantUsage.state == "reserved").order_by(AssistantUsage.id).with_for_update())).all())
    if not rows:
        if money(run.reserved or ZERO) or pending:
            raise RuntimeError("Assistant budget reservation is unavailable")
        return
    for usage in pending:
        await settle_call(db, run, usage, cost=None, unknown=True)
    remaining = money(run.reserved or ZERO)
    if any(row.reserved < remaining for row in rows):
        raise RuntimeError("Assistant budget reservation is inconsistent")
    for row in rows:
        row.reserved -= remaining
    run.reserved = ZERO
    await db.flush()


async def snapshot(db, owner_id, day, *, user_daily_limit, global_daily_limit, include_global=False):
    """Read current quota state; ordinary users do not receive global consumption."""
    if type(owner_id) is not int or owner_id <= 0 or not isinstance(day, date):
        raise ValueError("Invalid assistant budget query")
    result = {"day": day.isoformat(), "currency": "CNY"}
    targets = [("user", owner_id, user_daily_limit)]
    if include_global:
        targets.append(("global", 0, global_daily_limit))
    for scope, scope_id, configured_cap in targets:
        row = await db.scalar(select(AssistantBudget).where(AssistantBudget.day == day,
            AssistantBudget.scope == scope, AssistantBudget.scope_id == scope_id))
        cap = min(row.cap, money(configured_cap)) if row is not None else money(configured_cap)
        spent, reserved = (row.spent, row.reserved) if row is not None else (ZERO, ZERO)
        result[scope] = {"cap": str(cap), "spent": str(spent), "reserved": str(reserved),
            "available": str(max(ZERO, cap - spent - reserved)), "estimated": True}
    return result
