"""Approved demo policy, independent of model secrets and runtime resources."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os


@dataclass(frozen=True)
class AssistantSettings:
    enabled: bool = False
    allow_campus_data: bool = False
    retention_days: int = 7
    context_turns: int = 8
    context_max_bytes: int = 48000
    run_cost_limit: Decimal = Decimal("0.10")
    user_daily_limit: Decimal = Decimal("1")
    global_daily_limit: Decimal = Decimal("5")
    alert_ratio: Decimal = Decimal("0.8")
    user_concurrency: int = 1
    global_concurrency: int = 2
    run_timeout_s: int = 180
    queue_timeout_s: int = 120
    lease_s: int = 30
    poll_interval_s: float = 1
    max_model_calls: int = 4
    max_tool_calls: int = 6
    max_parallel_tools: int = 3
    max_retries: int = 1
    retry_delay_s: float = 0.25
    embedding_price_per_1m: Decimal | None = None
    embedding_price_version: str = ""

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.allow_campus_data) is not bool:
            raise ValueError("Assistant feature switches must be booleans")
        bounds = ((self.retention_days, 1, 30), (self.context_turns, 1, 20),
            (self.context_max_bytes, 4096, 64000), (self.user_concurrency, 1, 4),
            (self.global_concurrency, 1, 16), (self.run_timeout_s, 10, 600),
            (self.queue_timeout_s, 10, 600), (self.lease_s, 15, 120),
            (self.max_model_calls, 1, 8), (self.max_tool_calls, 1, 12),
            (self.max_parallel_tools, 1, 3), (self.max_retries, 0, 2))
        if any(type(value) is not int or not minimum <= value <= maximum for value, minimum, maximum in bounds):
            raise ValueError("Assistant policy is outside supported limits")
        if self.user_concurrency > self.global_concurrency:
            raise ValueError("Assistant user concurrency exceeds global capacity")
        for value in (self.run_cost_limit, self.user_daily_limit, self.global_daily_limit):
            if not isinstance(value, Decimal) or not value.is_finite() or not Decimal("0.00000001") <= value <= 1000:
                raise ValueError("Assistant budgets must be positive finite CNY amounts")
        if not self.run_cost_limit <= self.user_daily_limit <= self.global_daily_limit:
            raise ValueError("Assistant budget scopes must be nested")
        if not isinstance(self.alert_ratio, Decimal) or not self.alert_ratio.is_finite() or not 0 < self.alert_ratio < 1:
            raise ValueError("Assistant alert ratio must be between zero and one")
        for value in (self.poll_interval_s, self.retry_delay_s):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0.01 <= value <= 5:
                raise ValueError("Assistant scheduling intervals are invalid")
        if self.embedding_price_per_1m is not None:
            if (not isinstance(self.embedding_price_per_1m, Decimal) or not self.embedding_price_per_1m.is_finite()
                    or self.embedding_price_per_1m <= 0 or not self.embedding_price_version):
                raise ValueError("Configure an explicit positive embedding price and version")


def load_assistant_settings(environ=None):
    source = os.environ if environ is None else environ
    prefix = "CAMPUS_ASSISTANT_"

    def boolean(name, default):
        value = source.get(prefix + name, str(default)).lower().strip()
        if value not in {"true", "false"}:
            raise ValueError("Invalid assistant switch")
        return value == "true"

    def number(name, default, parser=int):
        return parser(source.get(prefix + name, str(default)))

    try:
        embedding = source.get(prefix + "EMBED_PRICE_PER_1M", "").strip()
        return AssistantSettings(enabled=boolean("ENABLED", False), allow_campus_data=boolean("ALLOW_CAMPUS_DATA", False),
            retention_days=number("RETENTION_DAYS", 7), context_turns=number("CONTEXT_TURNS", 8),
            context_max_bytes=number("CONTEXT_MAX_BYTES", 48000),
            run_cost_limit=number("RUN_COST_LIMIT_CNY", "0.10", Decimal),
            user_daily_limit=number("USER_DAILY_LIMIT_CNY", 1, Decimal),
            global_daily_limit=number("GLOBAL_DAILY_LIMIT_CNY", 5, Decimal),
            alert_ratio=number("ALERT_RATIO", "0.8", Decimal),
            user_concurrency=number("USER_CONCURRENCY", 1), global_concurrency=number("GLOBAL_CONCURRENCY", 2),
            run_timeout_s=number("RUN_TIMEOUT_S", 180), queue_timeout_s=number("QUEUE_TIMEOUT_S", 120),
            lease_s=number("LEASE_S", 30), poll_interval_s=number("POLL_INTERVAL_S", 1, float),
            max_model_calls=number("MAX_MODEL_CALLS", 4), max_tool_calls=number("MAX_TOOL_CALLS", 6),
            max_parallel_tools=number("MAX_PARALLEL_TOOLS", 3), max_retries=number("MAX_RETRIES", 1),
            retry_delay_s=number("RETRY_DELAY_S", ".25", float),
            embedding_price_per_1m=Decimal(embedding) if embedding else None,
            embedding_price_version=source.get(prefix + "EMBED_PRICE_VERSION", "").strip())
    except (ValueError, TypeError, InvalidOperation, AttributeError):
        raise ValueError("Assistant policy configuration is invalid") from None
