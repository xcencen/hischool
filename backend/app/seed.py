"""Insert campus demo accounts without replacing existing accounts or edits."""

import asyncio
from collections.abc import Mapping
import os

import bcrypt
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import validate_database_url
from app.database import Database
from app.models.user import User


DEMO_ACCOUNTS = (
    ("student", "demo_student", "演示学生"),
    ("teacher", "demo_teacher", "演示教师"),
    ("admin", "demo_admin", "演示管理员"),
)


def load_demo_passwords(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    passwords: dict[str, str] = {}
    for role, _, _ in DEMO_ACCOUNTS:
        variable = f"CAMPUS_DEMO_{role.upper()}_PASSWORD"
        password = source.get(variable, "")
        if not 8 <= len(password.encode("utf-8")) <= 72:
            raise ValueError(f"{variable} must contain 8 to 72 UTF-8 bytes")
        passwords[role] = password
    return passwords


async def ensure_demo_users(session: AsyncSession, passwords: Mapping[str, str]) -> list[str]:
    """Caller owns the transaction. Existing usernames are never updated."""
    for role, _, _ in DEMO_ACCOUNTS:
        password = passwords.get(role, "")
        if not 8 <= len(password.encode("utf-8")) <= 72:
            raise ValueError(f"Demo {role} password must contain 8 to 72 UTF-8 bytes")
    usernames = [username for _, username, _ in DEMO_ACCOUNTS]
    existing = set((await session.scalars(select(User.username).where(User.username.in_(usernames)))).all())
    created: list[str] = []
    for role, username, name in DEMO_ACCOUNTS:
        if username in existing:
            continue
        password_hash = bcrypt.hashpw(passwords[role].encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        statement = insert(User).values(
            username=username, password=password_hash, name=name, role=role,
            status=1, auth_version=0,
        )
        # A concurrent seed process may insert the same username first. Keep its row intact.
        statement = statement.on_duplicate_key_update(id=User.id)
        await session.execute(statement)
        created.append(username)
    await session.flush()
    return created


async def main() -> None:
    raw_url = os.environ.get("CAMPUS_DATABASE_URL", "")
    validate_database_url(raw_url)
    passwords = load_demo_passwords()
    database = Database(raw_url)
    try:
        async with database.session_factory() as session:
            async with session.begin():
                created = await ensure_demo_users(session, passwords)
        print("Demo seed finished; existing accounts retained.")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
