"""Decimal policy rejects ambiguous amounts before any persistence or provider call."""

from decimal import Decimal

import pytest

from app.assistant.budget import money


@pytest.mark.parametrize("value", [True, False, 0.1, None, "NaN", "Infinity", "-0.01", "1e40"])
def test_budget_money_rejects_unsafe_amounts(value):
    with pytest.raises(ValueError):
        money(value)


def test_budget_money_rounds_up_without_binary_float_or_free_tiny_requests():
    assert money("0.000000001") == Decimal("0.00000001")
    assert money(Decimal("0.1")) == Decimal("0.10000000")
    assert money(0) == Decimal("0.00000000")
