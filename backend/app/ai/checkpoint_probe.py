"""Explicit cross-process checkpoint verification, restricted to my_campus_test."""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import TypedDict
from uuid import uuid4


DATABASE_VARIABLE = "CAMPUS_CHECKPOINT_TEST_DATABASE_URL"


def connection_options(raw):
    from sqlalchemy.engine import make_url
    from app.config import validate_database_url

    validate_database_url(raw)
    url = make_url(raw)
    if url.database != "my_campus_test":
        raise ValueError("Checkpoint probes only permit my_campus_test")
    return dict(host=url.host, port=url.port or 3306, user=url.username,
                password=url.password or "", db=url.database, autocommit=True,
                charset="utf8mb4", connect_timeout=5, read_timeout=10,
                init_command="SET time_zone = '+00:00'")


@asynccontextmanager
async def saver_for(raw):
    options = connection_options(raw)
    import asyncmy
    from langgraph.checkpoint.mysql.asyncmy import AsyncMySaver

    # Native from_conn_string does not URL-decode passwords in the pinned version.
    connection = await asyncmy.connect(**options)
    try:
        yield AsyncMySaver(conn=connection)
    finally:
        await connection.ensure_closed()


def build_graph(saver):
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict):
        value: int

    graph = StateGraph(State)
    graph.add_node("increment", lambda state: {"value": state["value"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    return graph.compile(checkpointer=saver)


def validate_thread(thread):
    if not isinstance(thread, str) or not re.fullmatch(r"m1-probe-[0-9a-f]{32}", thread):
        raise ValueError("Invalid checkpoint probe thread")


async def write_state(raw, thread):
    validate_thread(thread)
    async with asyncio.timeout(45), saver_for(raw) as saver:
        # This function is called only after the explicit --allow-schema-setup flag.
        await saver.setup()
        await build_graph(saver).ainvoke({"value": 41}, {"configurable": {"thread_id": thread}})


async def read_state(raw, thread):
    validate_thread(thread)
    async with asyncio.timeout(20), saver_for(raw) as saver:
        graph = build_graph(saver)
        state = await graph.aget_state({"configurable": {"thread_id": thread}})
        other = await graph.aget_state({"configurable": {"thread_id": "m1-probe-" + "0" * 32}})
        return {"value_matches": state.values == {"value": 42},
                "completed": not state.next, "other_thread_empty": not other.values}


async def cleanup(raw, thread):
    validate_thread(thread)
    async with asyncio.timeout(20), saver_for(raw) as saver:
        await saver.adelete_thread(thread)
        graph = build_graph(saver)
        state = await graph.aget_state({"configurable": {"thread_id": thread}})
        return not state.values


def probe(raw, *, runner=None):
    connection_options(raw)  # Guard target before importing or contacting any driver.
    thread = "m1-probe-" + uuid4().hex
    result = {"status": "failed", "backend": "mysql", "cross_process": False}
    written = False
    try:
        asyncio.run(write_state(raw, thread))
        written = True
        environment = os.environ.copy()
        environment[DATABASE_VARIABLE] = raw
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        backend = Path(__file__).resolve().parents[2]
        environment["PYTHONPATH"] = str(backend)
        child = (runner or subprocess.run)(
            [sys.executable, "-B", "-m", "app.ai.checkpoint_probe", "--reader", thread],
            env=environment, cwd=backend, capture_output=True, text=True,
            timeout=30, check=False)
        if child.returncode:
            result["reason"] = "reader_failed"
        else:
            checks = json.loads(child.stdout)
            passed = all(checks.get(name) is True for name in (
                "value_matches", "completed", "other_thread_empty"))
            result.update(status="passed" if passed else "failed", cross_process=passed)
    except Exception:
        result["reason"] = "checkpoint_unavailable"
    finally:
        if written:
            try:
                result["cleanup_verified"] = asyncio.run(cleanup(raw, thread))
            except Exception:
                result["cleanup_verified"] = False
            if not result["cleanup_verified"]:
                result.update(status="failed", reason="cleanup_failed")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="M1 MySQL checkpointer test (writes isolated test schema)")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-schema-setup", action="store_true")
    parser.add_argument("--reader", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    raw = os.environ.get(DATABASE_VARIABLE, "")
    try:
        if options.reader:
            result = asyncio.run(read_state(raw, options.reader))
        elif options.live and options.allow_schema_setup:
            result = probe(raw)
        elif options.live or options.allow_schema_setup:
            result = {"status": "blocked", "reason": "explicit_schema_permission_required"}
        else:
            if raw:
                connection_options(raw)
            result = {"status": "not_run", "configured": bool(raw), "cross_process": False}
    except Exception:
        result = {"status": "blocked", "reason": "invalid_test_configuration"}
    print(json.dumps(result, sort_keys=True))
    if options.reader:
        return 0 if result.get("value_matches") else 1
    return 0 if result.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
