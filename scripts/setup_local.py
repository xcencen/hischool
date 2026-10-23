"""Prepare local Compose configuration without printing or replacing secrets."""

import argparse
from pathlib import Path
import secrets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("F:/my-campus-dev/data"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = root / ".env.compose"
    if config.exists():
        raise SystemExit(".env.compose already exists; preserved without changes.")
    data = arguments.data_root.resolve()
    if data.drive.upper() != "F:":
        raise SystemExit("The agreed local data directory must be on F:.")
    for folder in (data, Path(str(data) + "-tests")):
        for name in ("mysql", "redis", "uploads", "knowledge", "faiss"):
            (folder / name).mkdir(parents=True, exist_ok=True)
    password = secrets.token_hex(24)
    values = {
        "CAMPUS_DATA_ROOT": data.as_posix(),
        "CAMPUS_DB_PASSWORD": password,
        "CAMPUS_DB_ROOT_PASSWORD": secrets.token_hex(24),
        "CAMPUS_DATABASE_URL": f"mysql+asyncmy://my_campus:{password}@mysql:3306/my_campus?charset=utf8mb4",
        "CAMPUS_JWT_SECRET": secrets.token_hex(32),
        "CAMPUS_DEMO_ADMIN_PASSWORD": secrets.token_hex(12),
        "CAMPUS_DEMO_TEACHER_PASSWORD": secrets.token_hex(12),
        "CAMPUS_DEMO_STUDENT_PASSWORD": secrets.token_hex(12),
    }
    with config.open("x", encoding="utf-8", newline="\n") as output:
        output.write("# Local secrets. Do not commit or paste into chat.\n")
        output.writelines(f"{key}={value}\n" for key, value in values.items())
    print("Prepared .env.compose; secrets were not printed. Data will live on F:.")


if __name__ == "__main__":
    main()
