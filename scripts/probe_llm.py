"""Compatibility wrapper for the explicit Step 7 M1 probe."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ai.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["probe", *sys.argv[1:]]))
