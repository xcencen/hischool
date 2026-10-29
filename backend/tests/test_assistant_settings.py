from dataclasses import replace
from decimal import Decimal

import pytest

from app.assistant.settings import AssistantSettings, load_assistant_settings


def test_demo_policy_is_explicit_and_closed_by_default():
    settings = load_assistant_settings({})
    assert not settings.enabled and not settings.allow_campus_data
    assert (settings.run_cost_limit, settings.user_daily_limit, settings.global_daily_limit) == (
        Decimal(".10"), Decimal("1"), Decimal("5"))
    assert settings.alert_ratio == Decimal(".8") and settings.retention_days == 7


@pytest.mark.parametrize("changes", [{"enabled": 1}, {"retention_days": 0}, {"run_cost_limit": .1},
    {"run_cost_limit": Decimal("NaN")}, {"user_daily_limit": Decimal(".01")},
    {"user_concurrency": 3}, {"max_retries": 4}, {"max_parallel_tools": 10},
    {"embedding_price_per_1m": Decimal(".5")}, {"poll_interval_s": float("inf")}])
def test_invalid_policy_rejected(changes):
    with pytest.raises(ValueError):
        replace(AssistantSettings(), **changes)


def test_bad_config_reports_no_raw_values():
    with pytest.raises(ValueError) as error:
        load_assistant_settings({"CAMPUS_ASSISTANT_RUN_COST_LIMIT_CNY": "private-bad-value"})
    assert "private-bad-value" not in str(error.value)
