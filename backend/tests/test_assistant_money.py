"""Money DTOs must match the browser's fixed-point, eight-decimal contract."""
import asyncio
from datetime import date, datetime
from decimal import Decimal
import re
from types import SimpleNamespace

import pytest

from app.api.assistant import public_run
from app.assistant import budget
from app.assistant.schemas import alert_response, run_response


def row(amount):
    return SimpleNamespace(id=1, public_id="run", status="succeeded", reason=None,
        cancel_requested=False, model_calls=1, tool_calls=0, cost_limit=Decimal(".1"),
        reserved=amount, spent=amount, budget_day=date(2030, 1, 1),
        create_time=datetime(2030, 1, 1), started_at=None, finished_at=None, deadline_at=None,
        conversation_id=1)


def fixed(value, expected):
    assert re.fullmatch(r"\d+(?:\.\d{1,8})?", value), value
    assert value == expected


@pytest.mark.parametrize("value,expected", [("0E-8", "0.00000000"), ("1E-8", "0.00000001")])
def test_run_money_has_fixed_point_wire_format(value, expected):
    response = run_response(row(Decimal(value)))
    for key in ("reserved", "spent"):
        fixed(response[key], expected)


@pytest.mark.parametrize("value,expected", [("0E-8", "0.00000000"), ("1E-8", "0.00000001")])
def test_alert_money_has_fixed_point_wire_format(value, expected):
    response = alert_response(SimpleNamespace(id=1, day=date(2030, 1, 1), scope="run",
        kind="unknown_usage", amount=Decimal(value), cap=Decimal(value), acknowledged=False,
        create_time=datetime(2030, 1, 1)))
    for key in ("amount", "cap"):
        fixed(response[key], expected)


def test_empty_budget_snapshot_zero_matches_browser_money_contract():
    class EmptyDatabase:
        async def scalar(self, statement):
            return None
    response = asyncio.run(budget.snapshot(EmptyDatabase(), 1, date(2030, 1, 1),
        user_daily_limit=Decimal(1), global_daily_limit=Decimal(5)))
    for key in ("spent", "reserved"):
        fixed(response["user"][key], "0.00000000")


@pytest.mark.parametrize("value,expected", [("0E-8", "0.00000000"), ("1E-8", "0.00000001")])
def test_usage_money_has_fixed_point_wire_format(value, expected):
    usage = SimpleNamespace(kind="model", resource="synthetic", attempt=1, state="settled",
        reserved=Decimal(value), charged=Decimal(value), input_tokens=1, output_tokens=1,
        cache_read_tokens=None, usage_unknown=False, price_version="test", latency_ms=1)
    class ReadDatabase:
        async def scalar(self, statement):
            return "conversation"
        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: [usage])
    response = asyncio.run(public_run(ReadDatabase(), SimpleNamespace(id=1), row(Decimal(value)), include_usage=True))
    for key in ("reserved", "charged"):
        fixed(response["usage"][0][key], expected)
