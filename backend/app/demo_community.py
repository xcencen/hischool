"""Demonstration content only; no fabricated school policies or remote APIs."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert

from app.database import utc_now
from app.models.activity import Activity
from app.models.notice import Notice, NoticeCategory
from app.models.user import User


async def ensure_demo_community(session):
    admin = await session.scalar(select(User).where(User.username == "demo_admin", User.role == "admin", User.status == 1))
    if admin is None:
        return
    for code, name in (("general", "综合通知"), ("teaching", "教学安排")):
        statement = insert(NoticeCategory).values(code=code, name=name, status=1)
        await session.execute(statement.on_duplicate_key_update(id=NoticeCategory.id))
    category_id = await session.scalar(select(NoticeCategory.id).where(NoticeCategory.code == "general"))
    now = utc_now()
    statement = insert(Notice).values(code="DEMO-WELCOME", title="欢迎使用 my-campus 校园服务",
        content="本通知为演示数据。你可以查看课表、浏览通知和报名校园活动。具体校园规定以学校正式发布的资料为准。",
        category_id=category_id, owner_id=admin.id, state="published", revision=1, published_at=now)
    await session.execute(statement.on_duplicate_key_update(id=Notice.id))
    for code, title, days, location, capacity in (
        ("DEMO-CAMPUS-TOUR", "校园探索体验活动", 7, "校园服务中心（演示）", 30),
        ("DEMO-READING", "阅读分享交流会", 14, "学生活动室（演示）", 20),
    ):
        start = (now + timedelta(days=days)).replace(hour=6, minute=0, second=0, microsecond=0)
        statement = insert(Activity).values(code=code, title=title,
            content="本活动使用模拟数据，仅供校园服务平台演示。报名、取消和名额变更将真实保存。",
            location=location, start_time=start, end_time=start+timedelta(hours=2),
            registration_deadline=start-timedelta(days=1), capacity=capacity, enrolled_count=0,
            owner_id=admin.id, state="published", revision=1, published_at=now)
        await session.execute(statement.on_duplicate_key_update(id=Activity.id))
    await session.flush()
