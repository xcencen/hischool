"""Explicit CNY price versions; unknown usage is never reported as free."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import os

from app.ai.settings import MODEL_ID


@dataclass(frozen=True)
class PriceTable:
    input_per_1m: Decimal
    output_per_1m: Decimal
    cache_read_per_1m: Decimal
    version: str
    source: str
    currency: str = "CNY"

    def __post_init__(self):
        if self.currency != "CNY" or not self.version or not self.source:
            raise ValueError("Configure CNY pricing, version and source")
        for value in (self.input_per_1m, self.output_per_1m, self.cache_read_per_1m):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("Model prices must be finite nonnegative decimals")


def load_price_table(environ=None):
    source = os.environ if environ is None else environ
    names = ("CAMPUS_LLM_PRICE_INPUT_PER_1M", "CAMPUS_LLM_PRICE_OUTPUT_PER_1M",
             "CAMPUS_LLM_PRICE_CACHE_READ_PER_1M", "CAMPUS_LLM_PRICE_VERSION",
             "CAMPUS_LLM_PRICE_SOURCE")
    if not any(source.get(name) for name in names):
        return None
    if not all(source.get(name) for name in names):
        raise ValueError("The model price table is incomplete")
    try:
        rates = [Decimal(source[name]) for name in names[:3]]
    except (InvalidOperation, TypeError):
        raise ValueError("Model prices must be finite nonnegative decimals") from None
    return PriceTable(*rates, version=source[names[3]], source=source[names[4]],
                      currency=source.get("CAMPUS_LLM_PRICE_CURRENCY", "CNY"))


def pricing_config(*, table=None):
    table = table or load_price_table()
    return {"configured": table is not None, "currency": table.currency if table else None,
            "version": table.version if table else None}


def _count(value):
    return value if type(value) is int and value >= 0 else None


def compute_cost(model_id, usage, *, table=None, at: datetime | None = None):
    # Kept for caller compatibility; no unverified time-of-day discount is applied.
    if model_id != MODEL_ID:
        raise ValueError("Unknown campus model ID")
    table = table or load_price_table()
    usage = usage or {}
    input_tokens = _count(usage.get("input_tokens", usage.get("prompt_tokens")))
    output_tokens = _count(usage.get("output_tokens", usage.get("completion_tokens")))
    details = usage.get("input_token_details") or usage.get("prompt_tokens_details") or {}
    cached = _count(details.get("cache_read", details.get("cached_tokens")))
    complete = table is not None and input_tokens is not None and output_tokens is not None
    if cached is not None and input_tokens is not None and cached > input_tokens:
        raise ValueError("Cached input cannot exceed total input tokens")
    cost = None
    if complete:
        known_cache = cached or 0
        rate = table.input_per_1m if cached is not None else max(
            table.input_per_1m, table.cache_read_per_1m)
        cost = ((input_tokens - known_cache) * rate
                + known_cache * table.cache_read_per_1m
                + output_tokens * table.output_per_1m) / Decimal(1_000_000)
    return {"model_id": model_id, "currency": table.currency if table else None,
            "price_version": table.version if table else None,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cache_read_tokens": cached,
            "estimated": True, "cache_usage_unknown": cached is None,
            "usage_unknown": input_tokens is None or output_tokens is None,
            "total_cost": str(cost) if cost is not None else None}
