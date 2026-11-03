"""Disposable M5.5 rehearsal. Never point this helper at a deployed database.

Only the operator wrapper supplies the fixed project guard. All output is hashes,
counts and safe states; raw database rows and connection strings stay private.
"""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings
from app.database import Database, utc_now


PROJECT = "my-campus-ai-m5-release"


def guarded_url(target):
    project = os.environ.get("M5_RELEASE_PROJECT", "")
    if project != PROJECT and not re.fullmatch(r"my-campus-ai-m6-release(?:-[a-z0-9-]+)?", project):
        raise ValueError("Explicit isolated release guard required")
    variable = "CAMPUS_DATABASE_URL" if target == "source" else "CAMPUS_CHECKPOINT_TEST_DATABASE_URL"
    value = os.environ[variable]
    url = make_url(value)
    host = "test-mysql" if target == "source" else "checkpoint-mysql"
    if url.database != "my_campus_test" or url.host != host or url.port != 3306:
        raise ValueError("Release helper refuses this database target")
    return value


async def snapshot(target):
    database = Database(guarded_url(target))
    try:
        async with database.engine.connect() as connection:
            names = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
            result = {}
            for name in sorted(names):
                # Names come only from MySQL metadata, still quote defensively.
                quoted = "`" + name.replace("`", "``") + "`"
                rows = (await connection.execute(text("SELECT * FROM " + quoted))).mappings().all()
                encoded = sorted(json.dumps(dict(row), sort_keys=True, ensure_ascii=False,
                    default=str, separators=(",", ":")) for row in rows)
                result[name] = {"rows": len(rows), "sha256": hashlib.sha256(
                    "\n".join(encoded).encode("utf-8")).hexdigest()}
            versions = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all() if "alembic_version" in names else []
            return {"versions": sorted(versions), "tables": result}
    finally:
        await database.dispose()


def migrate(revision):
    guarded_url("source")
    subprocess.run([sys.executable, "-B", "-m", "alembic", "upgrade", revision],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def seed_campus():
    from app.models.user import User
    from app.models.notice import NoticeCategory
    database = Database(guarded_url("source"))
    try:
        async with database.session_factory() as db:
            db.add(User(username="m5_release_student", password="synthetic-unused-hash",
                name="合成校园迁移标记", role="student", status=1, auth_version=0,
                create_time=utc_now().replace(microsecond=123456)))
            db.add(NoticeCategory(code="m5-release", name="M5 合成备份分类", status=1))
            await db.commit()
    finally:
        await database.dispose()


def rollback():
    """Real worker process, MySQL accounting and campus HTTP; no cloud clients."""
    from fastapi.testclient import TestClient
    from app.assistant import budget, runs
    from app.assistant.settings import AssistantSettings
    from app.bootstrap.config import BootstrapSettings
    from app.main import create_app
    from app.models.assistant import AssistantBudget, AssistantMessage
    from app.utils.jwt import create_access_token
    # Reuse only the isolated test fixture, never a production seed/cleanup CLI.
    from test_assistant_runs_integration import World

    guarded_url("source")
    world = World()
    world.seed()
    runs.budget_day = lambda: world.day

    async def prepare(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        claimed = await runs.claim_next(database, cache, world.settings)
        assert claimed.public_id == queued.public_id
        async with database.session_factory() as db:
            row, _ = await runs._locked(db, claimed.public_id)
            await budget.start_call(db, row, call_key="release-interrupted", kind="model",
                upper_bound=Decimal(".03"), resource="synthetic-no-dispatch",
                price_snapshot={"version": "m5-release-synthetic"})
            row.lease_until = utc_now() - timedelta(seconds=1)
            message = await db.scalar(select(AssistantMessage).where(AssistantMessage.run_id == row.id))
            message.create_time = utc_now() - timedelta(days=8)
            await db.commit()
        return conversation.public_id, queued.public_id

    conversation_id, run_id = world.run(prepare)
    # Actual disabled entry point must work with no model/MCP/price environment.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CAMPUS_LLM_", "CAMPUS_MCP_", "CAMPUS_ASSISTANT_"))}
    env.update(CAMPUS_ASSISTANT_ENABLED="false", CAMPUS_ASSISTANT_ALLOW_CAMPUS_DATA="false")
    process = subprocess.Popen([sys.executable, "-B", "-m", "app.assistant.worker"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async def settled(database, cache):
            async with asyncio.timeout(20):
                while True:
                    assert process.poll() is None, "Closed maintenance process stopped"
                    row, usages, messages = await world.inspect(database, run_id)
                    if row.status == "failed" and all(item.content is None for item in messages):
                        assert row.reason == "interrupted" and row.spent == Decimal(".03") and row.reserved == 0
                        assert len(usages) == 1 and usages[0].state == "unknown"
                        assert usages[0].charged == Decimal(".03") and usages[0].usage_unknown
                        async with database.session_factory() as db:
                            buckets = (await db.scalars(select(AssistantBudget).where(AssistantBudget.day == world.day))).all()
                            assert len(buckets) == 2 and all(item.spent == Decimal(".03") and item.reserved == 0 for item in buckets)
                        return
                    await asyncio.sleep(.1)
        world.run(settled)
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert process.returncode == 0

    before = asyncio.run(snapshot("source"))
    app = create_app(BootstrapSettings(), mode="campus")
    app.state.assistant_settings = AssistantSettings(enabled=False, allow_campus_data=False)
    token = create_access_token(world.actors["a"].id, 0, world.campus)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == 200
        response = client.post(f"/api/assistant/conversations/{conversation_id}/runs",
            headers={"Authorization": "Bearer " + token},
            json={"content": "Synthetic closed-switch request", "request_key": "closed-release"})
        assert response.status_code == 503
    async def no_double_charge(database, cache):
        assert await runs.recover_abandoned(database) == 0
    world.run(no_double_charge)
    after = asyncio.run(snapshot("source"))
    financial = ("assistant_runs", "assistant_usage", "assistant_budgets", "assistant_alerts")
    assert all(before["tables"][name] == after["tables"][name] for name in financial)
    return {"new_run_http": 503, "campus_health_http": 200, "campus_ready_http": 200,
            "model_calls": 0, "maintenance_exit": process.returncode, "charged": "0.03000000",
            "retained_financial_tables": {name: after["tables"][name] for name in financial},
            "redacted_expired_body": True, "repeat_recovery_count": 0}


def main():
    mode = sys.argv[1]
    if mode == "prepare":
        assert not asyncio.run(snapshot("source"))["tables"], "Source must be empty"
        assert not asyncio.run(snapshot("restore"))["tables"], "Restore target must be empty"
        migrate("0005_knowledge")
        asyncio.run(seed_campus())
        result = asyncio.run(snapshot("source"))
        assert result["versions"] == ["0005_knowledge"]
    elif mode == "restored":
        source, restored = asyncio.run(snapshot("source")), asyncio.run(snapshot("restore"))
        assert source == restored, "Restored table/row/version hashes differ"
        result = restored
    elif mode == "upgrade":
        before = asyncio.run(snapshot("source"))
        assert before["versions"] == ["0005_knowledge"]
        migrate("0006_assistant")
        after = asyncio.run(snapshot("source"))
        assert after["versions"] == ["0006_assistant"]
        assert all(after["tables"][name] == data for name, data in before["tables"].items() if name != "alembic_version")
        migrate("0007_assistant_access")
        final = asyncio.run(snapshot("source"))
        assert final["versions"] == ["0007_assistant_access"]
        assert all(final["tables"][name] == data for name, data in after["tables"].items() if name != "alembic_version")
        after = final
        subprocess.run([sys.executable, "-B", "-m", "alembic", "check"], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = after
    elif mode == "rollback":
        result = rollback()
    else:
        raise ValueError("Unknown release rehearsal phase")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No exception objects: drivers can include connection data or row values.
        print("Isolated release phase failed", file=sys.stderr)
        raise SystemExit(1) from None
