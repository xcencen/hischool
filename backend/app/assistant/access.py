"""Pilot admission. Short mutations share the existing assistant control lock."""
import asyncio
import re

from sqlalchemy import func, select, update

from app.assistant.conversations import lock_control
from app.common.exceptions import BusinessException
from app.models.assistant_access import AssistantPolicy, AssistantAccess, AssistantConsent, AssistantRunAccess
from app.models.user import User


async def _current(db, user_id):
    policy = await db.scalar(select(AssistantPolicy).where(AssistantPolicy.current.is_(True))
                            .with_for_update(read=True))
    grant = await db.scalar(select(AssistantAccess).where(AssistantAccess.user_id == user_id)
                           .with_for_update(read=True).execution_options(populate_existing=True))
    confirmed = False
    if policy is not None and grant is not None and grant.eligible:
        confirmed = await db.scalar(select(AssistantConsent.id).where(
            AssistantConsent.user_id == user_id, AssistantConsent.policy_id == policy.id,
            AssistantConsent.generation == grant.generation).with_for_update(read=True)) is not None
    return policy, grant, confirmed


async def state(db, user_id, settings):
    policy, grant, confirmed = await _current(db, user_id)
    eligible = bool(grant and grant.eligible)
    return dict(eligible=eligible, consented=confirmed,
        can_run=bool(settings.enabled and settings.allow_campus_data and eligible and confirmed),
        generation=grant.generation if grant else 0,
        policy=dict(version=policy.version, title=policy.title, text=policy.text) if policy else None)


async def require_access(db, user_id, *, binding=None):
    policy, grant, confirmed = await _current(db, user_id)
    if not confirmed or policy is None or grant is None or not grant.eligible:
        raise BusinessException('尚未获得助手试用资格或未确认当前数据使用说明', code=403)
    if binding is not None and (binding.policy_id != policy.id or binding.generation != grant.generation):
        raise BusinessException('本次运行的助手授权已失效', code=403)
    return policy, grant


async def require_run(db, row):
    binding = await db.scalar(select(AssistantRunAccess).where(AssistantRunAccess.run_id == row.id)
                              .with_for_update(read=True))
    if binding is None:
        raise BusinessException('本次运行没有有效的助手授权', code=403)
    return await require_access(db, row.owner_id, binding=binding)


async def bind_run(db, row, policy, grant):
    db.add(AssistantRunAccess(run_id=row.id, policy_id=policy.id, generation=grant.generation))


def grant_response(user, grant):
    return dict(user_id=user.id, username=user.username, name=user.name,
                eligible=bool(grant and grant.eligible), generation=grant.generation if grant else 0)


async def list_access(db, *, page=1, page_size=20):
    count = await db.scalar(select(func.count()).select_from(User))
    rows = (await db.execute(select(User, AssistantAccess).outerjoin(AssistantAccess,
        AssistantAccess.user_id == User.id).order_by(User.id).offset((page-1)*page_size).limit(page_size))).all()
    return dict(list=[grant_response(user, grant) for user, grant in rows], total=count or 0, page=page, page_size=page_size)


async def set_eligibility(db, user_id, eligible, expected_generation, *, actor=None):
    if type(eligible) is not bool or type(expected_generation) is not int or expected_generation < 0:
        raise BusinessException('资格参数无效', code=422)
    await lock_control(db, actor)
    user = await db.get(User, user_id)
    if user is None:
        raise BusinessException('用户不存在', code=404)
    grant = await db.scalar(select(AssistantAccess).where(AssistantAccess.user_id == user_id)
                            .with_for_update().execution_options(populate_existing=True))
    if (grant.generation if grant else 0) != expected_generation:
        raise BusinessException('资格已变更，请刷新后重试', code=409)
    if grant is None:
        grant = AssistantAccess(user_id=user_id, eligible=eligible, generation=1)
        db.add(grant)
    elif grant.eligible != eligible:
        grant.eligible = eligible
        grant.generation += 1
    await db.commit()
    return grant_response(user, grant)


async def consent(db, actor, policy_version):
    await lock_control(db, actor)
    policy, grant, confirmed = await _current(db, actor.id)
    if policy is None or policy.version != policy_version:
        raise BusinessException('数据使用说明已更新，请重新阅读', code=409)
    if grant is None or not grant.eligible:
        raise BusinessException('尚未获得助手试用资格', code=403)
    if not confirmed:
        db.add(AssistantConsent(user_id=actor.id, generation=grant.generation, policy_id=policy.id))
    await db.commit()


async def withdraw(db, actor):
    await lock_control(db, actor)
    _, grant, confirmed = await _current(db, actor.id)
    if grant is not None and confirmed:
        grant.generation += 1
    await db.commit()


async def publish_policy(db, version, title, text):
    if (type(version) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', version)
            or type(title) is not str or not 1 <= len(title.strip()) <= 100
            or type(text) is not str or not 1 <= len(text.strip()) <= 8000):
        raise BusinessException('告知文本或版本无效', code=422)
    await lock_control(db)
    if await db.scalar(select(AssistantPolicy.id).where(AssistantPolicy.version == version)) is not None:
        raise BusinessException('告知版本不可复用', code=409)
    await db.execute(update(AssistantPolicy).where(AssistantPolicy.current.is_(True)).values(current=False))
    policy = AssistantPolicy(version=version, title=title.strip(), text=text.strip(), current=True)
    db.add(policy)
    await db.commit()
    return policy


def main():
    """Explicit local publication, never called by initialization or a worker."""
    import argparse
    from pathlib import Path
    from app.config import load_settings
    from app.database import Database
    parser = argparse.ArgumentParser(description='Publish an approved assistant notice; does not enable the assistant.')
    parser.add_argument('--version', required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--approved', action='store_true', required=True)
    args = parser.parse_args()
    async def publish():
        database = Database(load_settings().database_url)
        try:
            async with asyncio.timeout(10):
                async with database.session_factory() as db:
                    await publish_policy(db, args.version, args.title, args.file.read_text(encoding='utf-8'))
        finally:
            await database.dispose()
    try:
        asyncio.run(publish())
    except Exception:
        print('assistant_policy status=failed')
        raise SystemExit(1) from None
    print('assistant_policy status=published')


if __name__ == '__main__':
    main()
