"""Safe monitor aggregation against the disposable MySQL assistant schema."""
from datetime import datetime, timedelta
from decimal import Decimal
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import update

from test_assistant_runs_integration import World, initialize, world
from app.database import utc_now
from app.models.assistant import AssistantMessage, AssistantRun, AssistantUsage, Conversation

pytestmark = pytest.mark.skipif(os.environ.get("CAMPUS_ASSISTANT_INTEGRATION") != "1",
    reason="Requires isolated assistant MySQL/Redis")


def test_monitor_counts_due_work_and_separates_embedding_upper_bound(world):
    from app.assistant.operations import snapshot

    async def action(database, cache):
        now = utc_now()
        conversation = await world.conversation(database)
        async with database.session_factory() as db:
            before = await snapshot(db, world.settings, now=now)
            for status in ("queued", "running", "failed"):
                run = AssistantRun(public_id=str(uuid4()), conversation_id=conversation.id,
                    owner_id=world.actors["a"].id, request_key=uuid4().hex, request_hash="0"*64,
                    status=status, reason="SECRET not a safe reason" if status == "failed" else None,
                    available_at=now-timedelta(seconds=200), deadline_at=now-timedelta(seconds=61),
                    lease_until=now-timedelta(seconds=61) if status == "running" else None,
                    finished_at=now-timedelta(seconds=61) if status == "failed" else None,
                    create_time=now-timedelta(seconds=200), budget_day=world.day,
                    cost_limit=Decimal(".1"), reserved=Decimal(".01") if status == "failed" else 0)
                db.add(run)
                await db.flush()
                if status == "failed":
                    for kind in ("model", "embedding"):
                        db.add(AssistantUsage(run_id=run.id, call_key=kind, kind=kind,
                            state="unknown", reserved=Decimal(".01"), charged=Decimal(".01"),
                            usage_unknown=True, resource="SECRET resource"))
            db.add(AssistantMessage(conversation_id=conversation.id, run_id=run.id, sequence=1, role="user",
                content="SECRET body", citations=[{"SECRET":"citation"}],
                create_time=now-timedelta(days=7, seconds=61)))
            await db.commit()
        async with database.session_factory() as db:
            result = await snapshot(db, world.settings, now=now)
            assert result["queued"]["count"] == before["queued"]["count"]+1
            assert result["queued"]["overdue_count"] == before["queued"]["overdue_count"]+1
            assert result["expired_leases"]["count"] == before["expired_leases"]["count"]+1
            assert result["terminal_reserved"]["count"] == before["terminal_reserved"]["count"]+1
            assert result["cleanup"]["count"] == before["cleanup"]["count"]+1
            assert result["costs"]["model_unknown_count"] == before["costs"]["model_unknown_count"]+1
            assert result["costs"]["embedding_conservative_count"] == before["costs"]["embedding_conservative_count"]+1
            assert set(result["warnings"]) >= {"queued_overdue", "expired_leases", "terminal_reserved", "cleanup_overdue", "model_usage_unknown"}
            assert "SECRET" not in json.dumps(result)
            assert {row["reason"] for row in result["failed_reasons"]} >= {"other"}
    world.run(action)


def test_sixty_second_grace_does_not_warn_early(world):
    from app.assistant.operations import snapshot

    async def action(database, cache):
        now = datetime(2000, 1, 1)
        conversation = await world.conversation(database)
        async with database.session_factory() as db:
            db.add(AssistantRun(public_id=str(uuid4()), conversation_id=conversation.id,
                owner_id=world.actors["a"].id, request_key=uuid4().hex, request_hash="0"*64,
                status="queued", available_at=now-timedelta(seconds=200),
                deadline_at=now-timedelta(seconds=60), budget_day=world.day, cost_limit=Decimal(".1")))
            await db.commit()
        async with database.session_factory() as db:
            result = await snapshot(db, world.settings, now=now)
            assert result["queued"]["overdue_count"] >= 1
            assert "queued_overdue" not in result["warnings"]
    world.run(action)
