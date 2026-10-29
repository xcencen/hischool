"""Fenced worker callbacks: persist an intent, dispatch once, then settle it.

Only short SQL transactions hold the control lock. Network requests never do.
The provider and MCP transport are injected so the orchestration can be tested
without exporting campus data or spending money.
"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
import logging
import time

import jwt
from sqlalchemy import select

from app.ai.pricing import compute_cost
from app.ai.settings import MODEL_ID
from app.assistant import budget, conversations, runs
from app.assistant.graph import execute_graph
from app.assistant.providers import ProviderFailure
from app.models.assistant import AssistantMessage, AssistantUsage, Conversation
from app.utils.jwt import AUDIENCE, ISSUER


logger = logging.getLogger(__name__)


class RunExecutor:
    def __init__(self, database, redis, campus_settings, settings, prices, provider, tool_client):
        self.database, self.redis = database, redis
        self.campus_settings, self.settings, self.prices = campus_settings, settings, prices
        self.provider, self.tool_client = provider, tool_client

    async def guard(self):
        await runs.guard(self.database, self.redis, self.public_id, self.lease_token, self.settings)

    @runs.bounded_sql
    async def _intent(self, *, kind, upper, resource, snapshot, attempt):
        await self.guard()
        async with self.database.session_factory() as db:
            row, _ = await runs._locked(db, self.public_id)
            runs.check_lease(row, self.lease_token)
            field = "model_calls" if kind == "model" else "tool_calls"
            maximum = self.settings.max_model_calls if kind == "model" else self.settings.max_tool_calls
            count = getattr(row, field)
            if count >= maximum:
                raise runs.RunStopped("model_limit" if kind == "model" else "tool_limit")
            try:
                usage = await budget.start_call(db, row, call_key=f"{field}-{count+1}", kind=kind,
                    upper_bound=upper, resource=resource, price_snapshot=snapshot, attempt=attempt)
            except budget.BudgetExceeded:
                # Keep the denial alert, but no request has been dispatched.
                await db.commit()
                raise
            setattr(row, field, count + 1)
            await db.commit()
            return usage.id

    @runs.bounded_sql
    async def _settle(self, usage_id, *, cost=None, unknown=False, elapsed=0, counts=None):
        # Settlement is allowed after cancellation/deadline, while this worker
        # still owns the lease. A stale worker cannot overwrite recovery.
        async with self.database.session_factory() as db:
            row, _ = await runs._locked(db, self.public_id)
            if row.status != "running" or row.lease_token != self.lease_token:
                raise runs.RunStopped("lease_lost")
            usage = await db.get(AssistantUsage, usage_id)
            values = counts or {}
            current = await budget.settle_call(db, row, usage, cost=cost, unknown=unknown,
                latency_ms=max(0, int(elapsed * 1000)), input_tokens=values.get("input_tokens"),
                output_tokens=values.get("output_tokens"), cache_read_tokens=values.get("cache_read_tokens"),
                price_version=values.get("price_version"))
            overrun = current.charged > current.reserved or row.spent > row.cost_limit
            await db.commit()
            if overrun:
                raise budget.BudgetExceeded()

    async def model_call(self, messages):
        upper = self.provider.estimate(messages)
        snapshot = {"version": self.prices.version, "currency": "CNY",
            "input_per_1m": str(self.prices.input_per_1m),
            "output_per_1m": str(self.prices.output_per_1m),
            "cache_read_per_1m": str(self.prices.cache_read_per_1m)}
        for attempt in range(1, self.settings.max_retries + 2):
            usage_id = await self._intent(kind="model", upper=upper, resource=MODEL_ID,
                                          snapshot=snapshot, attempt=attempt)
            started = time.monotonic()
            try:
                reply = await self.provider.complete(messages)
            except asyncio.CancelledError:
                await self._settle(usage_id, unknown=True, elapsed=time.monotonic()-started)
                raise
            except ProviderFailure as error:
                await self._settle(usage_id, cost=Decimal(0), unknown=error.uncertain,
                                   elapsed=time.monotonic()-started)
                if error.retryable and not error.uncertain and attempt <= self.settings.max_retries:
                    await self.guard()
                    await asyncio.sleep(self.settings.retry_delay_s * attempt)
                    continue
                raise
            except Exception:
                await self._settle(usage_id, unknown=True, elapsed=time.monotonic()-started)
                raise ProviderFailure("unavailable") from None
            values = compute_cost(MODEL_ID, reply.usage, table=self.prices)
            unknown = values["total_cost"] is None
            await self._settle(usage_id, cost=values["total_cost"], unknown=unknown,
                               elapsed=time.monotonic()-started, counts=values)
            if unknown:
                raise runs.RunStopped("usage_unknown")
            await self.guard()
            return reply

    def _assertion(self):
        # Reconstitute a short assertion from the original, revocable login
        # binding. No raw browser JWT is stored; MCP receives only its own
        # delegated credential through CampusMCPClient.
        now = int(datetime.now(UTC).timestamp())
        return jwt.encode({"sub": str(self.owner_id), "auth_version": self.auth_version,
            "jti": self.source_jti, "iat": now, "exp": min(self.source_exp, now + 60),
            "iss": ISSUER, "aud": AUDIENCE}, self.campus_settings.jwt_secret,
            algorithm=self.campus_settings.jwt_algorithm)

    async def tool_call(self, name, arguments, call_id):
        knowledge = name == "campus_search_knowledge"
        upper, kind, snapshot = Decimal(0), "tool", {"pricing": "internal_read_only"}
        if knowledge:
            rate = self.settings.embedding_price_per_1m
            if rate is None:
                raise runs.RunStopped("pricing_missing")
            # M2 may perform at most three embedding attempts; byte length is a
            # conservative token upper bound. It does not expose billed usage.
            upper = budget.money(Decimal(len(arguments["query"].encode("utf-8")) * 3)
                                 * rate / Decimal(1_000_000))
            kind = "embedding"
            snapshot = {"version": self.settings.embedding_price_version,
                "input_per_1m": str(rate), "attempts_upper": 3, "usage": "unknown_upper_bound"}
        for attempt in range(1, (1 if knowledge else self.settings.max_retries + 1) + 1):
            usage_id = await self._intent(kind=kind, upper=upper, resource=name,
                                          snapshot=snapshot, attempt=attempt)
            started = time.monotonic()
            try:
                value = await self.tool_client.call(name, arguments, campus_token=self._assertion(), run_id=self.public_id)
            except asyncio.CancelledError:
                await self._settle(usage_id, cost=Decimal(0), unknown=knowledge, elapsed=time.monotonic()-started)
                raise
            except Exception:
                await self._settle(usage_id, cost=Decimal(0), unknown=knowledge, elapsed=time.monotonic()-started)
                raise ProviderFailure("unavailable") from None
            await self._settle(usage_id, cost=Decimal(0), unknown=knowledge, elapsed=time.monotonic()-started,
                counts={"price_version": self.settings.embedding_price_version if knowledge else None})
            await self.guard()
            reason = value.get("reason")
            if reason in {"unauthenticated", "forbidden"}:
                raise runs.RunStopped(reason)
            if (not knowledge and not value.get("ok") and reason in {"unavailable", "rate_limited", "timeout"}
                    and attempt <= self.settings.max_retries):
                await asyncio.sleep(self.settings.retry_delay_s * attempt)
                continue
            return value

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(self.settings.lease_s / 3)
            await self.guard()

    async def execute(self, row):
        self.public_id, self.lease_token = row.public_id, row.lease_token
        self.owner_id, self.auth_version = row.owner_id, row.auth_version
        self.source_jti, self.source_exp = row.source_jti, row.source_exp
        heartbeat = execution = None
        status, reason, result = "failed", "unavailable", None
        try:
            await self.guard()
            async with self.database.session_factory() as db:
                conversation = await db.get(Conversation, row.conversation_id)
                messages = await conversations.context_messages(db, conversation, self.settings)
                message = await db.scalar(select(AssistantMessage).where(
                    AssistantMessage.run_id == row.id, AssistantMessage.role == "user"))
                if message is None or not message.content:
                    raise runs.RunStopped("context_expired")
                messages.append({"role": "user", "content": message.content})
            execution = asyncio.create_task(execute_graph(messages=messages, model_call=self.model_call,
                tool_call=self.tool_call, guard=self.guard, max_steps=self.settings.max_model_calls,
                max_tool_calls=self.settings.max_tool_calls, max_parallel_tools=self.settings.max_parallel_tools,
                context_max_bytes=self.settings.context_max_bytes))
            heartbeat = asyncio.create_task(self._heartbeat())
            done, _ = await asyncio.wait({execution, heartbeat}, return_when=asyncio.FIRST_COMPLETED,
                                        timeout=self.settings.run_timeout_s)
            if not done:
                raise runs.RunStopped("timeout")
            if heartbeat in done:
                await heartbeat
                raise runs.RunStopped("unavailable")
            result = await execution
            await self.guard()
            status, reason = "succeeded", None
        except asyncio.CancelledError:
            status, reason = "cancelled", "worker_stopped"
            raise
        except budget.BudgetExceeded:
            reason = "budget_exceeded"
        except (runs.RunStopped, ProviderFailure) as error:
            reason = error.reason
            status = "cancelled" if reason == "cancelled" else "failed"
        except Exception:
            reason = "unavailable"
        finally:
            # Cancel and join all network work before releasing reservations.
            for task in (execution, heartbeat):
                if task is not None and not task.done():
                    task.cancel()
            for task in (execution, heartbeat):
                if task is not None:
                    with suppress(asyncio.CancelledError, Exception):
                        await task
            try:
                await runs.finish(self.database, self.public_id, self.lease_token, status=status, reason=reason,
                    text=result.text if result is not None else None,
                    citations=result.citations if result is not None else None, redis=self.redis)
            except Exception:
                # A dead database or expired fencing token is handled by the
                # next recovery tick, never by replaying the model request.
                logger.warning("assistant_run run_id=%s status=deferred", self.public_id)
            with suppress(Exception):
                await self.provider.aclose()
            logger.info("assistant_run run_id=%s status=%s reason=%s", self.public_id, status, reason)
