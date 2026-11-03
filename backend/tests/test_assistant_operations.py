"""Monitor failures must stay unavailable, never become healthy empty counters."""
import asyncio

import pytest


def test_unavailable_database_is_not_zero():
    from app.assistant.operations import OperationsUnavailable, snapshot
    from app.assistant.settings import AssistantSettings

    class BrokenDatabase:
        async def execute(self, statement):
            raise RuntimeError("SECRET database endpoint and query")

    with pytest.raises(OperationsUnavailable) as error:
        asyncio.run(snapshot(BrokenDatabase(), AssistantSettings()))
    assert str(error.value) == "Assistant operations unavailable"


def test_deadline_is_unavailable(monkeypatch):
    from app.assistant import operations
    from app.assistant.settings import AssistantSettings

    class StalledDatabase:
        async def execute(self, statement):
            await asyncio.Event().wait()

    monkeypatch.setattr(operations, "DEADLINE_S", .01)
    with pytest.raises(operations.OperationsUnavailable):
        asyncio.run(operations.snapshot(StalledDatabase(), AssistantSettings()))


