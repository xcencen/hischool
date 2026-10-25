"""Safe M1 operator entry point. Live requests require explicit flags and prices."""

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from app.ai.pricing import load_price_table
from app.ai.probe import ProbeUnavailable, live_probe, offline_probe
from app.ai.settings import load_llm_settings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 7 M1 assistant capability probe")
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--live", action="store_true", help="Send four synthetic, billable requests")
    probe.add_argument("--max-cost-cny", help="Explicit approved ceiling, at most 5 CNY")
    probe.add_argument("--check-thinking", action="store_true", help="Two additional paid on/off checks")
    probe.add_argument("--report", type=Path, help="Optional local safe-summary report")
    options = parser.parse_args(argv)
    try:
        settings, table = load_llm_settings(), load_price_table()
        if options.live:
            if not options.max_cost_cny:
                raise ProbeUnavailable("budget_required")
            try:
                limit = Decimal(options.max_cost_cny)
            except InvalidOperation:
                raise ProbeUnavailable("invalid_budget") from None
            result = asyncio.run(live_probe(settings, table, max_cost=limit,
                                           check_thinking=options.check_thinking))
        else:
            if options.max_cost_cny or options.check_thinking:
                parser.error("--max-cost-cny and --check-thinking require --live")
            result = offline_probe(settings, table)
    except ProbeUnavailable as error:
        result = {"status": "blocked", "reason": error.reason, "requests": 0}
    except (ValueError, TypeError):
        result = {"status": "blocked", "reason": "invalid_configuration", "requests": 0}
    except Exception:
        result = {"status": "failed", "reason": "unavailable"}
    output = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if options.report:
        try:
            options.report.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents overwriting previous evidence or config.
            with options.report.open("x", encoding="utf-8") as report:
                report.write(output + "\n")
        except OSError:
            print(json.dumps({"status": "failed", "reason": "report_write_failed"}))
            return 1
    print(output)
    if options.live:
        return 0 if result["status"] == "passed" else 1
    return 0 if result.get("configured") else 2


if __name__ == "__main__":
    raise SystemExit(main())
