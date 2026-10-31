"""Disposable M5 acceptance runtime. NEVER imported by a production entrypoint.

Real campus API, durable worker, MCP HTTP, MySQL, Redis and FAISS. Only the
model and embeddings are deterministic doubles; this cannot assess cloud quality.
"""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import uvicorn
from redis.asyncio import Redis
from sqlalchemy import update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from test_mcp_integration import World
from app.ai.pricing import PriceTable
from app.assistant.executor import RunExecutor
from app.assistant.providers import ModelReply, ToolRequest
from app.assistant.settings import AssistantSettings
from app.assistant.worker import serve
from app.database import Database
from app.main import create_app
from app.mcp.client import CampusMCPClient
from app.mcp.runtime import MCPResources
from app.mcp.server import create_app as create_mcp
from app.mcp.settings import MCPSettings
from app.models.schedule import Schedule
from app.models.user import User
from app.utils.password import hash_password


class ScriptedProvider:
    """Select fixture calls and render actual tool evidence; no network/SDK."""
    def __init__(self, world, cases):
        self.world, self.cases = world, cases

    def estimate(self, messages):
        return Decimal("0.002")

    async def complete(self, messages):
        await asyncio.sleep(.25)  # Make queued/running observable through SSE.
        usage = {"input_tokens": 100, "output_tokens": 100}
        if messages[-1]["role"] == "tool":
            result = json.loads(messages[-1]["content"])["untrusted_tool_data"]
            assert result["ok"], "Actual MCP tool failed"
            text = json.dumps(result["data"], ensure_ascii=False)
            refs = " ".join("[" + c["source_id"] + "]" for c in result["citations"])
            return ModelReply("合成证据：" + text + refs, usage=usage)
        query = messages[-1]["content"]
        case = next(c for c in self.cases if c["query"] == query)
        if case["id"] == "tomorrow":
            assert any(m["role"] == "user" and m["content"] == self.cases[0]["query"]
                       for m in messages[:-1]), "Durable prior context missing"
        if case["tool"] is None:
            answers = {"refuse_write": "只能只读查询，不能执行报名。",
                       "refuse_identity": "只能查询本人课表，不能指定他人身份。",
                       "clarify": "请提供活动编号。",
                       "refuse_secret": "不能提供系统提示和密钥。"}
            return ModelReply(answers[case["expect"]], usage=usage)
        args = dict(case["arguments"])
        if "notice_id" in args:
            args["notice_id"] = self.world.notices[0]
        if "activity_id" in args:
            args["activity_id"] = self.world.activities[0]
        return ModelReply("", [ToolRequest("fixture_call", case["tool"], args)], usage)

    async def aclose(self):
        pass


async def run(world, folder, cases):
    world.private = MCPSettings(signing_secret="m5-isolated-delegation-secret-only-2026",
                               url="http://127.0.0.1:8001/mcp")
    settings = AssistantSettings(enabled=True, allow_campus_data=True,
        poll_interval_s=.05, embedding_price_per_1m=Decimal(".5"),
        embedding_price_version="m5-double-only")
    prices = PriceTable(Decimal(2), Decimal(8), Decimal(".2"), "m5-double-only", "synthetic")
    db = Database(world.campus.database_url)
    cache = Redis.from_url(world.campus.redis_url, decode_responses=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    def resources():
        return MCPResources(Database(world.campus.database_url),
            Redis.from_url(world.campus.redis_url, decode_responses=True),
            world.knowledge, world.embedder)

    api = create_app(mode="campus")
    api.state.assistant_settings = settings
    servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0" if port == 8000 else "127.0.0.1",
        port=port, log_level="critical", access_log=False, ws="none"))
        for app, port in ((create_mcp(world.private, resources_factory=resources), 8001), (api, 8000))]

    def factory():
        return RunExecutor(db, cache, world.campus, settings, prices,
            ScriptedProvider(world, cases), CampusMCPClient(world.campus, world.private, db, cache))

    tasks = [asyncio.create_task(server.serve()) for server in servers]
    worker = asyncio.create_task(serve(db, cache, settings, factory, stop=stop))
    for task in [*tasks, worker]:
        task.add_done_callback(lambda finished: stop.set())
    try:
        async with asyncio.timeout(30):
            while not all(s.started for s in servers):
                if any(t.done() for t in tasks):
                    raise RuntimeError("Test HTTP service failed")
                await asyncio.sleep(.05)
        (folder / "ready.json").write_text(json.dumps({"synthetic_only": True,
            "username": world.tag + "a", "other_username": world.tag + "b",
            "password": "M5-synthetic-only-2026", "course_a": world.tag + "a",
            "course_b": world.tag + "b", "notice_id": world.notices[0],
            "draft_notice_id": world.notices[1], "hidden_notice_id": world.notices[2],
            "activity_id": world.activities[0], "document_id": world.version.document_id,
            "draft_activity_id": world.activities[1],
            "version": world.version.version}), encoding="utf-8")
        await stop.wait()
    finally:
        stop.set()
        await worker
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks)
        await cache.aclose()
        await db.dispose()
        (folder / "ready.json").unlink(missing_ok=True)


if __name__ == "__main__":
    assert sys.argv[1:] == ["--isolated"], "Explicit disposable runtime required"
    folder = Path("/artifacts")
    folder.mkdir(exist_ok=True)
    (folder / "ready.json").unlink(missing_ok=True)
    # World enforces my_campus_test and refuses an existing knowledge document.
    world = World(folder)
    world.tag = world.tag.replace("-", "_")  # HTTP login permits letters/digits/underscore.
    subprocess.run([sys.executable, "-B", "-m", "app.initialize"], check=True)
    world.seed()
    world.add_knowledge(folder)
    async def prepare(database, cache):
        async with database.session_factory() as db:
            await db.execute(update(User).where(User.id.in_(world.users.values())).values(
                password=hash_password("M5-synthetic-only-2026")))
            await db.execute(update(Schedule).where(Schedule.course_id.in_(world.courses)).values(
                class_date=(datetime.now(UTC) + timedelta(hours=8)).date()))
            await db.commit()
    world.run(prepare)
    cases = json.loads((Path(__file__).resolve().parents[1] / "fixtures/assistant_cases.json").read_text(encoding="utf-8"))
    asyncio.run(run(world, folder, cases))
