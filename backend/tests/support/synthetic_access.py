"""Explicit test-only enrollment. Never imported by application code."""
from sqlalchemy import select
from app.assistant import access
from app.models.assistant_access import AssistantPolicy


async def enroll(db, actors):
    policy = await db.scalar(select(AssistantPolicy).where(AssistantPolicy.current.is_(True)))
    if policy is None:
        policy = await access.publish_policy(db, 'synthetic-test-only', 'Synthetic notice', 'Synthetic data only; no cloud calls.')
    for actor in actors:
        state = await access.state(db, actor.id, type('Settings', (), {'enabled': True, 'allow_campus_data': True})())
        if not state['eligible']:
            await access.set_eligibility(db, actor.id, True, state['generation'])
        await access.consent(db, actor, policy.version)
