"""Operator-only explicit M3 synthetic probe. No dotenv or production DB access."""

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
import json


def main(argv=None):
    parser = argparse.ArgumentParser(description="M3 synthetic assistant acceptance")
    parser.add_argument("command", choices=["probe"])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-cost-cny")
    options = parser.parse_args(argv)
    if not options.live or not options.max_cost_cny:
        parser.error("probe requires --live and an explicitly authorized --max-cost-cny (at most 5)")
    try:
        from app.ai.pricing import load_price_table
        from app.ai.settings import load_llm_settings
        from app.assistant.probe import live_probe
        result = asyncio.run(live_probe(load_llm_settings(), load_price_table(),
                                       max_cost=Decimal(options.max_cost_cny)))
    except (ValueError, TypeError, InvalidOperation):
        result = {"status": "blocked", "reason": "invalid_configuration", "requests": 0}
    except Exception:
        result = {"status": "failed", "reason": "unavailable"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
