"""One-shot Compose task: migrate first, then insert missing demo accounts."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    from app.config import load_settings

    load_settings()  # Validate target and secrets before any schema mutation.
    backend = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend / "alembic.ini"), "upgrade", "head"],
        cwd=backend, check=True,
    )
    subprocess.run([sys.executable, "-m", "app.seed"], cwd=backend, check=True)


if __name__ == "__main__":
    main()
