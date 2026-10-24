"""Opt-in smoke checks against this project's running Compose stack only."""

import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


SNAPSHOT = """
import asyncio, hashlib, json
from sqlalchemy import select
from app.config import load_settings
from app.database import Database
from app.models.user import User
from app.models.course import Course
from app.models.enrollment import CourseEnrollment
from app.models.schedule import Schedule
from app.models.notice import Notice, NoticeCategory
from app.models.activity import Activity, ActivityRegistration
async def snapshot():
    db = Database(load_settings().database_url)
    try:
        async with db.session_factory() as session:
            rows = (await session.execute(select(User.id, User.username, User.name,
                User.role, User.status, User.create_time).order_by(User.id))).all()
            assert len(rows) >= 3, 'Demo users missing'
            courses = (await session.execute(select(Course.id, Course.code, Course.name,
                Course.teacher_id, Course.status, Course.description).order_by(Course.id))).all()
            enrollments = (await session.execute(select(CourseEnrollment.id,
                CourseEnrollment.course_id, CourseEnrollment.user_id).order_by(CourseEnrollment.id))).all()
            lessons = (await session.execute(select(Schedule.id, Schedule.course_id, Schedule.class_date,
                Schedule.start_time, Schedule.end_time, Schedule.period, Schedule.location)
                .order_by(Schedule.id))).all()
            assert len(courses) >= 2 and len(lessons) >= 3, 'Demo timetable missing'
            data = {'users': [list(row) for row in rows], 'courses': [list(row) for row in courses],
                    'enrollments': [list(row) for row in enrollments], 'lessons': [list(row) for row in lessons]}
            for model in (NoticeCategory, Notice, Activity, ActivityRegistration):
                records = (await session.execute(select(*model.__table__.columns).order_by(model.id))).all()
                data[model.__tablename__] = [list(row) for row in records]
            print(hashlib.sha256(json.dumps(data,
                default=str, ensure_ascii=False).encode()).hexdigest())
    finally:
        await db.dispose()
asyncio.run(snapshot())
"""

WORKER = """
import time
from redis import Redis
from rq import Queue
from app.config import load_settings
from app.jobs import worker_probe
connection = Redis.from_url(load_settings().redis_url)
job = Queue('knowledge', connection=connection).enqueue(worker_probe,
    'my-campus-worker-probe', result_ttl=120, failure_ttl=120, job_timeout=15)
try:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        job.refresh()
        if job.is_finished:
            assert job.return_value() == 'my-campus-worker-probe'
            print('Actual knowledge worker completed the probe')
            break
        if job.is_failed:
            raise RuntimeError('Worker probe failed')
        time.sleep(1)
    else:
        raise RuntimeError('Worker did not consume the knowledge queue within 45s')
finally:
    job.delete()
    connection.close()
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default="docker", help="Docker executable, if not on PATH")
    parser.add_argument("--exercise-restarts", action="store_true",
                        help="Temporarily stop/restart only this project's demo containers")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not (root / ".env.compose").is_file():
        raise SystemExit("Run scripts/setup_local.py first")
    prefix = [options.docker, "compose", "--env-file", str(root / ".env.compose"),
              "-f", str(root / "compose.yaml"), "--project-name", "my-campus"]

    def compose(*arguments: str) -> str:
        result = subprocess.run([*prefix, *arguments], cwd=root, capture_output=True,
                                text=True, timeout=150, check=False)
        if result.returncode != 0:
            # A CLI error may include resolved settings; keep secrets out of output.
            raise RuntimeError("Compose command failed; inspect the named service locally")
        return result.stdout.strip()

    def readiness(code: int, *, mysql: bool, redis: bool, port: int = 8000) -> None:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                try:
                    response = urlopen(f"http://127.0.0.1:{port}/api/ready", timeout=7)
                except HTTPError as error:
                    response = error
                with response:
                    status = response.status
                    payload = json.load(response)
                if status == code and payload.get("data") == {"mysql": mysql, "redis": redis}:
                    return
            except (URLError, ValueError, TimeoutError, ConnectionError):
                pass
            time.sleep(1)
        raise RuntimeError(f"Readiness check did not reach HTTP {code}")

    def snapshot() -> str:
        return compose("exec", "-T", "api", "python", "-c", SNAPSHOT)

    readiness(200, mysql=True, redis=True)
    readiness(200, mysql=True, redis=True, port=5173)
    with urlopen("http://127.0.0.1:5173/", timeout=10) as response:
        assert response.status == 200 and "my-campus" in response.read().decode()
    original = snapshot()
    compose("exec", "-T", "api", "python", "-c", WORKER)
    print("PASS: API, frontend proxy, seeded data and actual RQ worker")

    if options.exercise_restarts:
        stopped: set[str] = set()
        try:
            compose("stop", "mysql")
            stopped.add("mysql")
            readiness(503, mysql=False, redis=True)
            compose("start", "mysql")
            stopped.remove("mysql")
            readiness(200, mysql=True, redis=True)
            compose("stop", "redis")
            stopped.add("redis")
            readiness(503, mysql=True, redis=False)
            compose("start", "redis")
            stopped.remove("redis")
            readiness(200, mysql=True, redis=True)
            compose("restart", "mysql", "redis", "api", "worker", "frontend")
            readiness(200, mysql=True, redis=True)
            readiness(200, mysql=True, redis=True, port=5173)
            assert snapshot() == original, "Campus records changed across container restarts"
            compose("exec", "-T", "api", "python", "-c", WORKER)
            print("PASS: dependency outage returns 503; restart preserves data and worker access")
        finally:
            if stopped:
                compose("start", *sorted(stopped))
    else:
        print("SKIP: outage/restart checks; add --exercise-restarts to include them")


if __name__ == "__main__":
    main()
