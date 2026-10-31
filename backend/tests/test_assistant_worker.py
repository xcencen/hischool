"""Standalone scheduling/maintenance without a database or cloud service."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph", reason="Requires optional assistant profile")
pytest.importorskip("mcp", reason="Requires optional assistant profile")

from app.assistant import worker
from app.assistant.settings import AssistantSettings


class Database:
    def __init__(self):
        self.disposed = False

    @asynccontextmanager
    async def session_factory(self):
        yield self

    async def dispose(self):
        self.disposed = True


def test_disabled_worker_recovers_and_purges_without_claiming_or_creating_clients(monkeypatch):
    events = []
    async def run():
        stop = asyncio.Event()
        async def recover(database):
            events.append("recover")
        async def purge(db, settings):
            events.append("purge")
            stop.set()
        monkeypatch.setattr(worker.runs, "recover_abandoned", recover)
        monkeypatch.setattr(worker.conversations, "purge_expired", purge)
        monkeypatch.setattr(worker.runs, "claim_next", lambda *args: pytest.fail("Unexpected claim"))
        await worker.serve(Database(), object(), AssistantSettings(),
            lambda: pytest.fail("Unexpected model/tool client"), stop=stop)
    asyncio.run(run())
    assert events == ["recover", "purge"]


def test_disabled_main_requires_neither_model_prices_mcp_secret_nor_tracing(monkeypatch):
    database = Database()
    cache = SimpleNamespace(closed=False)
    async def close():
        cache.closed = True
    cache.aclose = close
    monkeypatch.setattr(worker, "load_assistant_settings", lambda: AssistantSettings())
    monkeypatch.setattr(worker, "load_settings", lambda: SimpleNamespace(database_url="unused",redis_url="unused"))
    for name in ("load_llm_settings", "load_price_table", "load_mcp_settings", "check_private_runtime"):
        monkeypatch.setattr(worker, name, lambda: pytest.fail("Disabled maintenance loaded model configuration"))
    monkeypatch.setattr(worker, "Database", lambda *args: database)
    monkeypatch.setattr(worker.Redis, "from_url", lambda *args,**kwargs: cache)
    async def serve(db, redis, settings, factory, **kwargs):
        assert db is database and redis is cache and not settings.enabled
    monkeypatch.setattr(worker, "serve", serve)
    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)
        await worker.main()
    asyncio.run(run())
    assert database.disposed and cache.closed


def test_windows_main_preserves_maintenance_without_linux_marker(monkeypatch):
    database = Database()
    cache = SimpleNamespace()
    async def close():
        pass
    cache.aclose = close
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="nt"), raising=False)
    monkeypatch.setattr(worker, "load_assistant_settings", lambda: AssistantSettings())
    monkeypatch.setattr(worker, "load_settings", lambda: SimpleNamespace(database_url="unused", redis_url="unused"))
    monkeypatch.setattr(worker, "Database", lambda *args: database)
    monkeypatch.setattr(worker.Redis, "from_url", lambda *args, **kwargs: cache)
    monkeypatch.setattr(worker, "HealthWriter", lambda: pytest.fail("Windows must not create a /tmp marker"))
    async def serve(db, redis, settings, factory, **kwargs):
        assert kwargs["heartbeat"] is None
    monkeypatch.setattr(worker, "serve", serve)
    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)
        await worker.main()
    asyncio.run(run())
    assert database.disposed


def test_local_concurrency_is_bounded_and_shutdown_joins_running_executions(monkeypatch):
    async def run():
        stop, entered = asyncio.Event(), asyncio.Event()
        active = peak = claimed = cancelled = 0
        async def nothing(*args, **kwargs):
            pass
        monkeypatch.setattr(worker.runs, "recover_abandoned", nothing)
        monkeypatch.setattr(worker.conversations, "purge_expired", nothing)
        async def claim(*args):
            nonlocal claimed
            claimed += 1
            return SimpleNamespace(id=claimed)
        monkeypatch.setattr(worker.runs, "claim_next", claim)
        class Executor:
            async def execute(self, row):
                nonlocal active, peak, cancelled
                active += 1
                peak = max(peak, active)
                if active == 2:
                    entered.set()
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    cancelled += 1
                    raise
                finally:
                    active -= 1
        settings = replace(AssistantSettings(),enabled=True,allow_campus_data=True,poll_interval_s=0.01)
        task = asyncio.create_task(worker.serve(Database(), object(), settings, Executor, stop=stop))
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert claimed == peak == 2
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        assert active == 0 and cancelled == 2
    asyncio.run(run())


def test_finished_task_exceptions_are_retrieved_without_payload_logging(monkeypatch, caplog):
    async def run():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        unhandled = []
        loop.set_exception_handler(lambda loop, context: unhandled.append(context))
        async def nothing(*args, **kwargs):
            pass
        monkeypatch.setattr(worker.runs, "recover_abandoned", nothing)
        monkeypatch.setattr(worker.conversations, "purge_expired", nothing)
        claims = 0
        async def claim(*args):
            nonlocal claims
            claims += 1
            if claims == 1:
                return object()
            if claims >= 3:
                stop.set()
            return None
        monkeypatch.setattr(worker.runs, "claim_next", claim)
        class Executor:
            async def execute(self, row):
                raise RuntimeError("private-worker-exception")
        settings=replace(AssistantSettings(),enabled=True,allow_campus_data=True,poll_interval_s=0.01)
        await worker.serve(Database(), object(), settings, Executor, stop=stop)
        assert not unhandled
    asyncio.run(run())
    assert "assistant_task status=failed" in caplog.text and "private-worker-exception" not in caplog.text


@pytest.mark.parametrize("switches", [(False, False), (True, False), (False, True)])
def test_health_records_maintenance_only_after_success_with_switches_off(monkeypatch, switches):
    async def run():
        stop = asyncio.Event()
        events = []
        async def recover(database):
            events.append("recover")
        async def purge(db, settings):
            events.append("purge")
            stop.set()
        def heartbeat(**state):
            if state.get("maintained"):
                events.append("maintained")
                assert state["mode"] == "maintenance"
        monkeypatch.setattr(worker.runs, "recover_abandoned", recover)
        monkeypatch.setattr(worker.conversations, "purge_expired", purge)
        settings = replace(AssistantSettings(), enabled=switches[0], allow_campus_data=switches[1])
        await worker.serve(Database(), object(), settings, lambda: pytest.fail("Unexpected client"),
                           stop=stop, heartbeat=heartbeat)
        assert events == ["recover", "purge", "maintained"]
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["recovery", "purge"])
def test_failed_maintenance_never_marks_worker_healthy(monkeypatch, failure):
    async def run():
        states = []
        async def recover(database):
            if failure == "recovery":
                raise RuntimeError("synthetic maintenance failure")
        async def purge(db, settings):
            raise RuntimeError("synthetic maintenance failure")
        monkeypatch.setattr(worker.runs, "recover_abandoned", recover)
        monkeypatch.setattr(worker.conversations, "purge_expired", purge)
        with pytest.raises(RuntimeError):
            await worker.serve(Database(), object(), AssistantSettings(), object,
                               heartbeat=lambda **state: states.append(state))
        assert not any(state.get("maintained") for state in states)
    asyncio.run(run())
