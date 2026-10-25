"""Read-only service adapters with fresh identity checks and bounded DTOs."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
import logging
import time
from uuid import uuid4

from pydantic import ValidationError

from app.common.exceptions import BusinessException
from app.infra.redis import RedisUnavailable, rate_limit
from app.mcp.auth import resolve_delegation
from app.mcp.catalog import TOOLS, ToolOutcome
from app.services import activity_service, knowledge_service, notice_service, schedule_service


logger = logging.getLogger(__name__)
MAX_RESULT_BYTES = 65536


def outcome(tool, *, run_id=None, data=None, citations=None, reason=None):
    return ToolOutcome(tool=tool if tool in TOOLS else "unknown", run_id=run_id,
        ok=reason is None, data=data, citations=citations or [], reason=reason,
        retryable=reason in {"rate_limited", "timeout", "unavailable"},
        observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z")).model_dump(mode="json")


@dataclass(frozen=True)
class ToolLimits:
    user: int = 30
    global_: int = 120
    knowledge_user: int = 5
    knowledge_global: int = 20

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (
                self.user, self.global_, self.knowledge_user, self.knowledge_global)):
            raise ValueError("Invalid MCP tool limits")


def citation(kind, item, position):
    if kind == "knowledge":
        return dict(source_id=f"S{position}", kind=kind, item_id=item["document_id"],
            title=item["document_title"], version=item["version"], page_number=item["page_number"],
            page_label=item["page_label"], chapter=item["chapter"], chunk_id=item["chunk_id"],
            url=f"/api/knowledge/documents/{item['document_id']}/source?version={item['version']}#page={item['page_number']}")
    path = "/app/schedule" if kind == "schedule" else f"/app/{'notices' if kind == 'notice' else 'activities'}/{item['id']}"
    return dict(source_id=f"S{position}", kind=kind, item_id=item["id"],
                title=item["course_name"] if kind == "schedule" else item["title"], url=path)


def publication_data(value, kind, *, limit, personal=False):
    raw = value.model_dump(mode="json")
    fields = ("id", "title", "category_id", "category_name", "published_at") if kind == "notice" else (
        "id", "title", "location", "start_time", "end_time", "registration_deadline", "capacity",
        "enrolled_count")
    if kind == "activity" and personal:
        fields += ("registration_status", "can_register", "can_cancel")
    result = {key: raw[key] for key in fields}
    result.update(content=raw["content"][:limit], truncated=len(raw["content"]) > limit)
    return result


class ToolExecutor:
    def __init__(self, resources, settings, *, limits=None):
        self.resources, self.settings = resources, settings
        self.limits = limits or ToolLimits()

    async def identity(self, token, *, tool=None):
        return await resolve_delegation(self.resources.database, self.resources.redis,
                                        self.settings, token, tool=tool)

    async def _limit(self, user_id, tool):
        limits = [("global", self.limits.global_), (f"user:{user_id}", self.limits.user)]
        if tool == "campus_search_knowledge":
            limits.extend([("knowledge:global", self.limits.knowledge_global),
                           (f"knowledge:user:{user_id}", self.limits.knowledge_user)])
        for key, capacity in limits:
            if not await rate_limit("mcp:" + key, capacity=capacity, refill_per_s=capacity / 60,
                                    client=self.resources.redis):
                raise BusinessException("工具调用过于频繁", code=429)

    async def execute(self, name, arguments, token):
        request_id, started = uuid4().hex, time.monotonic()
        run_id, reason = None, None
        safe_name = name if name in TOOLS else "unknown"
        try:
            if name not in TOOLS:
                reason = "unknown_tool"
                return outcome("unknown", reason="unknown_tool")
            # Validate the raw dictionary, before SDK dependency filtering/coercion.
            args = TOOLS[name].arguments.model_validate(arguments)
            user, claims = await self.identity(token, tool=name)
            run_id = claims.run_id
            await self._limit(user.id, name)
            timeout = self.settings.knowledge_timeout_s if name == "campus_search_knowledge" else self.settings.query_timeout_s
            remaining = claims.exp - time.time()
            if remaining <= 0:
                raise BusinessException("MCP 身份凭证已失效", code=401)
            async with asyncio.timeout(min(timeout, remaining)):
                async with self.resources.database.session_factory() as db:
                    data, citations = await self._query(db, name, args, user)
                # Use a new read view after all network/file/database awaits.
                await self.identity(token, tool=name)
            result = outcome(name, run_id=run_id, data=data, citations=citations)
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
                reason = "invalid_response"
                return outcome(name, run_id=run_id, reason="invalid_response")
            return result
        except ValidationError:
            reason = "invalid_arguments" if run_id is None else "invalid_response"
        except BusinessException as error:
            reason = {401: "unauthenticated", 403: "forbidden", 404: "not_found",
                      429: "rate_limited"}.get(error.code, "unavailable")
        except TimeoutError:
            reason = "timeout"
        except RedisUnavailable:
            reason = "unavailable"
        except asyncio.CancelledError:
            reason = "cancelled"
            raise
        except Exception:
            reason = "unavailable"
        finally:
            logger.info("mcp_tool request_id=%s tool=%s outcome=%s elapsed_ms=%d", request_id,
                safe_name, reason or "completed", int((time.monotonic() - started) * 1000))
        return outcome(name, run_id=run_id, reason=reason)

    async def _query(self, db, name, args, user):
        if name == "campus_get_my_schedules":
            today = schedule_service.shanghai_today()
            reference = today + timedelta(days=1) if args.date == "tomorrow" else (
                today if args.date in {"today", "this_week"} else date.fromisoformat(args.date))
            start, end = schedule_service.week_bounds(reference) if args.date == "this_week" else (reference, reference)
            rows = await schedule_service.list_schedules(db, user=user, start=start, end=end, limit=51)
            fields = ("id", "course_id", "course_name", "course_code", "class_date", "start_time",
                      "end_time", "period", "location")
            items = [{key: row.model_dump(mode="json")[key] for key in fields} for row in rows[:50]]
            return dict(start_date=start.isoformat(), end_date=end.isoformat(), timezone="Asia/Shanghai",
                items=items, truncated=len(rows) > 50), [citation("schedule", item, i + 1) for i, item in enumerate(items)]
        if name == "campus_list_notices":
            page = await notice_service.list_notices(db, args.page, args.page_size, args.keyword,
                                                    args.category_id, actor=None)
            items = [publication_data(row, "notice", limit=600) for row in page.list]
            return dict(items=items, total=page.total, page=args.page, page_size=args.page_size), [
                citation("notice", item, i + 1) for i, item in enumerate(items)]
        if name == "campus_get_notice":
            item = publication_data(await notice_service.detail(db, args.notice_id, actor=None), "notice", limit=4000)
            return item, [citation("notice", item, 1)]
        if name == "campus_list_activities":
            page = await activity_service.list_activities(db, args.page, args.page_size, args.keyword, actor=None)
            items = [publication_data(row, "activity", limit=600) for row in page.list]
            return dict(items=items, total=page.total, page=args.page, page_size=args.page_size), [
                citation("activity", item, i + 1) for i, item in enumerate(items)]
        if name == "campus_get_activity":
            item = publication_data(await activity_service.detail(db, args.activity_id, actor=None, viewer=user),
                                    "activity", limit=4000, personal=True)
            return item, [citation("activity", item, 1)]
        if self.resources.knowledge_settings is None:
            raise BusinessException("知识库配置无效", code=503)
        value = await knowledge_service.search(db, self.resources.knowledge_settings, args.query, args.top_k,
                                               embedder=self.resources.embedder)
        return dict(index_version=value["index_version"], results=value["results"],
                    insufficient=value["insufficient"]), [
            citation("knowledge", item, i + 1) for i, item in enumerate(value["results"])]
