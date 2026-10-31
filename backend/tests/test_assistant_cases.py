"""Versioned evaluation inputs must agree with the executable read-only catalog.

This checks evaluation contracts, not real-model answer quality.
"""
import json
from pathlib import Path

from app.mcp.catalog import TOOLS


def test_evaluation_cases_cover_exact_readonly_catalog_and_strict_arguments():
    cases = json.loads((Path(__file__).parent / "fixtures/assistant_cases.json").read_text(encoding="utf-8"))
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["tool"] for case in cases if case["tool"]} == set(TOOLS)
    for case in cases:
        assert case["query"].strip()
        if case["tool"]:
            TOOLS[case["tool"]].arguments.model_validate(case["arguments"])
        else:
            assert case["expect"] in {"refuse_write", "refuse_identity", "clarify", "refuse_secret"}
            assert case["arguments"] == {}
