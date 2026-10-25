"""M1 settings, explicit prices and safe offline entry points."""

from decimal import Decimal
import json

import pytest

from app.ai import cli
from app.ai.checkpoint_probe import connection_options, validate_thread
from app.ai.pricing import PriceTable, compute_cost, load_price_table
from app.ai.probe import ProbeUnavailable, budget_reservation
from app.ai.settings import LLMSettings, MODEL_ID, load_llm_settings
from app.config import load_settings


def price_table():
    return PriceTable(Decimal("2"), Decimal("3"), Decimal("0.2"), "2026-10-test", "test-only")


def test_chat_settings_are_independent_and_do_not_leak_credentials():
    settings = load_llm_settings({"CAMPUS_LLM_API_KEY": "private-key-marker",
        "CAMPUS_LLM_BASE_URL": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/"})
    assert settings.configured and settings.model_id == MODEL_ID
    assert "private-key-marker" not in repr(settings)
    assert "workspace" not in repr(settings)
    assert settings.enable_thinking is False


@pytest.mark.parametrize("endpoint", [
    "http://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope.aliyuncs.com.evil.test/compatible-mode/v1",
    "https://workspace.cn-beijing.maas.aliyuncs.com.evil.test/compatible-mode/v1",
    "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "https://private:password@dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope.aliyuncs.com:8000/compatible-mode/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1?api_key=private",
    "https://dashscope.aliyuncs.com/compatible-mode/v1#private",
    "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
])
def test_chat_rejects_unapproved_endpoints(endpoint):
    with pytest.raises(ValueError) as error:
        load_llm_settings({"CAMPUS_LLM_BASE_URL": endpoint})
    assert endpoint not in str(error.value)


@pytest.mark.parametrize("key,value", [
    ("CAMPUS_LLM_MODEL_ID", "unapproved-private-value"),
    ("CAMPUS_LLM_TIMEOUT_S", "0"), ("CAMPUS_LLM_TIMEOUT_S", "46"),
    ("CAMPUS_LLM_TIMEOUT_S", "invalid"),
    ("CAMPUS_LLM_MAX_OUTPUT_TOKENS", "63"),
    ("CAMPUS_LLM_MAX_OUTPUT_TOKENS", "2049"),
    ("CAMPUS_LLM_ENABLE_THINKING", "maybe"),
])
def test_chat_configuration_fails_explicitly(key, value):
    with pytest.raises(ValueError):
        load_llm_settings({key: value})


def test_invalid_optional_chat_configuration_does_not_break_campus():
    settings = load_settings({"CAMPUS_DATABASE_URL": "mysql+asyncmy://user:password@localhost/my_campus",
        "CAMPUS_REDIS_URL": "redis://localhost/0", "CAMPUS_JWT_SECRET": "x" * 40,
        "CAMPUS_LLM_TIMEOUT_S": "invalid", "CAMPUS_LLM_MODEL_ID": "unapproved"})
    assert settings.jwt_algorithm == "HS256"


def test_price_or_usage_missing_is_unknown_instead_of_zero(monkeypatch):
    for name in tuple(__import__("os").environ):
        if name.startswith("CAMPUS_LLM_PRICE_"):
            monkeypatch.delenv(name)
    assert load_price_table({}) is None
    assert compute_cost(MODEL_ID, {"input_tokens": 10, "output_tokens": 5})["total_cost"] is None
    result = compute_cost(MODEL_ID, {}, table=price_table())
    assert result["usage_unknown"] and result["total_cost"] is None


def test_cost_uses_decimal_cache_split_and_counts_reasoning_only_once():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "input_token_details": {"cache_read": 500_000},
             "output_token_details": {"reasoning": 500_000}}
    result = compute_cost(MODEL_ID, usage, table=price_table())
    assert Decimal(result["total_cost"]) == Decimal("4.1")
    assert result["currency"] == "CNY" and not result["usage_unknown"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "not-a-price"])
def test_price_rejects_invalid_values_without_echoing_them(value):
    values = {"CAMPUS_LLM_PRICE_INPUT_PER_1M": value,
        "CAMPUS_LLM_PRICE_OUTPUT_PER_1M": "3", "CAMPUS_LLM_PRICE_CACHE_READ_PER_1M": "0.2",
        "CAMPUS_LLM_PRICE_VERSION": "test", "CAMPUS_LLM_PRICE_SOURCE": "test"}
    with pytest.raises(ValueError):
        load_price_table(values)


def test_partial_price_table_and_invalid_usage_are_rejected():
    with pytest.raises(ValueError):
        load_price_table({"CAMPUS_LLM_PRICE_INPUT_PER_1M": "2"})
    with pytest.raises(ValueError):
        compute_cost(MODEL_ID, {"input_tokens": 1, "output_tokens": 0,
            "input_token_details": {"cache_read": 2}}, table=price_table())


def test_budget_preflight_is_explicit_and_conservative():
    with pytest.raises(ProbeUnavailable, match="could not complete"):
        budget_reservation(None, Decimal("5"))
    with pytest.raises(ProbeUnavailable):
        budget_reservation(price_table(), Decimal("0.000001"))
    with pytest.raises(ProbeUnavailable):
        budget_reservation(price_table(), Decimal("5.01"))
    assert Decimal("0") < budget_reservation(price_table(), Decimal("5")) < Decimal("5")


def test_offline_cli_does_not_create_clients_or_files(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_llm_settings", lambda: LLMSettings())
    monkeypatch.setattr(cli, "load_price_table", lambda: None)
    monkeypatch.setattr(cli, "live_probe", lambda *a, **k: pytest.fail("unexpected network path"))
    assert cli.main(["probe"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "not_configured" and not result["live_verified"]
    assert not list(tmp_path.iterdir())


def test_live_cli_requires_budget_and_does_not_overwrite_evidence(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "load_llm_settings", lambda: LLMSettings())
    monkeypatch.setattr(cli, "load_price_table", lambda: None)
    assert cli.main(["probe", "--live"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "budget_required"
    evidence = tmp_path / "report.json"
    evidence.write_text("existing evidence", encoding="utf-8")
    assert cli.main(["probe", "--report", str(evidence)]) == 1
    assert evidence.read_text() == "existing evidence"


@pytest.mark.parametrize("url", [
    "mysql+asyncmy://user:private-password@localhost/my_campus",
    "mysql+pymysql://user:private-password@localhost/my_campus_test",
    "mysql+asyncmy://user:private-password@localhost/my_campus_test?db=my_campus",
])
def test_checkpoint_probe_refuses_non_test_targets_before_connecting(url):
    with pytest.raises(ValueError) as error:
        connection_options(url)
    assert "private-password" not in str(error.value)


def test_checkpoint_decodes_password_and_bounds_network_timeouts():
    options = connection_options("mysql+asyncmy://user:p%40ss%3Aword@localhost/my_campus_test")
    assert options["password"] == "p@ss:word" and options["autocommit"]
    assert options["connect_timeout"] == 5 and options["read_timeout"] == 10
    with pytest.raises(ValueError):
        validate_thread("another-users-thread")
