"""Real isolated admission/revocation transactions; no external providers."""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from test_assistant_runs_integration import World, MockProvider, BlockingProvider, initialize, world
from app.assistant import access, runs, stream
from app.common.exceptions import BusinessException
from app.models.assistant import AssistantRun, AssistantBudget

pytestmark = pytest.mark.skipif(os.environ.get('CAMPUS_ASSISTANT_INTEGRATION') != '1', reason='Requires isolated assistant MySQL/Redis')


def test_denied_admission_has_no_run_or_reservation(world):
    async def action(database, cache):
        actor = world.actors['a']
        async with database.session_factory() as db:
            current = await access.state(db, actor.id, world.settings)
            await access.set_eligibility(db, actor.id, False, current['generation'])
        conversation = await world.conversation(database)
        with pytest.raises(BusinessException) as error:
            await world.submit(database, cache, conversation)
        assert error.value.code == 403
        async with database.session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(AssistantRun).where(AssistantRun.owner_id == actor.id)) == 0
            assert await db.scalar(select(AssistantBudget.id).where(AssistantBudget.scope == 'user', AssistantBudget.scope_id == actor.id)) is None
    world.run(action)


def test_consent_version_and_generation_cannot_be_reused(world):
    async def action(database, cache):
        actor = world.actors['a']
        async with database.session_factory() as db:
            before = await access.state(db, actor.id, world.settings)
            await access.withdraw(db, actor)
            after = await access.state(db, actor.id, world.settings)
            assert after['eligible'] and not after['consented'] and not after['can_run']
            assert after['generation'] > before['generation']
            await access.consent(db, actor, before['policy']['version'])
            assert (await access.state(db, actor.id, world.settings))['can_run']
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        async with database.session_factory() as db:
            await access.publish_policy(db, 'new-' + uuid4().hex, 'Synthetic notice', 'Only synthetic test data.')
            with pytest.raises(BusinessException) as error:
                await access.consent(db, actor, before['policy']['version'])
            assert error.value.code == 409
        assert await runs.claim_next(database, cache, world.settings) is None
        final, _, messages = await world.inspect(database, queued.public_id)
        assert final.status == 'failed' and final.reason == 'access_revoked' and final.reserved == 0
        assert all(message.role != 'assistant' for message in messages)
    world.run(action)


def test_regrant_does_not_resurrect_queued_run(world):
    async def action(database, cache):
        actor = world.actors['a']
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        async with database.session_factory() as db:
            before = await access.state(db, actor.id, world.settings)
            denied = await access.set_eligibility(db, actor.id, False, before['generation'])
            await access.set_eligibility(db, actor.id, True, denied['generation'])
            await access.consent(db, actor, before['policy']['version'])
        assert await runs.claim_next(database, cache, world.settings) is None
        final, _, _ = await world.inspect(database, queued.public_id)
        assert final.reason == 'access_revoked' and final.reserved == 0
        new = await world.submit(database, cache, conversation)
        assert new.id != queued.id
    world.run(action)


def test_withdraw_during_provider_settles_without_publishing(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        row = await runs.claim_next(database, cache, world.settings)
        provider = BlockingProvider()
        pending = asyncio.create_task(world.executor(database, cache, provider).execute(row))
        await asyncio.wait_for(provider.entered.wait(), 3)
        async with database.session_factory() as db:
            await access.withdraw(db, world.actors['a'])
        await asyncio.wait_for(pending, 8)
        final, usage, messages = await world.inspect(database, queued.public_id)
        assert provider.cancelled and final.reason == 'access_revoked'
        assert final.reserved == 0 and usage[0].state == 'unknown'
        assert not any(message.role == 'assistant' for message in messages)
    world.run(action)


def test_withdraw_before_final_commit_prevents_result_and_stream_replay(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        row = await runs.claim_next(database, cache, world.settings)
        async with database.session_factory() as db:
            await access.withdraw(db, world.actors['a'])
        await runs.finish(database, row.public_id, row.lease_token, status='succeeded',
                          text='Must not publish', citations=[], redis=cache)
        final, _, messages = await world.inspect(database, queued.public_id)
        assert final.reason == 'access_revoked' and final.reserved == 0
        assert not any(message.role == 'assistant' for message in messages)
        with pytest.raises(BusinessException) as error:
            await stream.snapshot(database, cache, world.settings, row.public_id,
                                  stream.Identity.from_payload(world.payloads['a']))
        assert error.value.code == 403
    world.run(action)


def test_completed_history_remains_owner_readable_after_withdraw(world):
    async def action(database, cache):
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        row = await runs.claim_next(database, cache, world.settings)
        await world.executor(database, cache, MockProvider()).execute(row)
        async with database.session_factory() as db:
            await access.withdraw(db, world.actors['a'])
        final, _, messages = await world.inspect(database, queued.public_id)
        assert final.status == 'succeeded' and messages[-1].content == 'Synthetic answer'
    world.run(action)


def test_revoke_transaction_serializes_concurrent_result_commit(world):
    async def action(database, cache):
        from app.assistant.conversations import lock_control
        conversation = await world.conversation(database)
        queued = await world.submit(database, cache, conversation)
        row = await runs.claim_next(database, cache, world.settings)
        async with database.session_factory() as db:
            await lock_control(db)
            finishing = asyncio.create_task(runs.finish(database, row.public_id, row.lease_token,
                status='succeeded', text='Must not publish', citations=[], redis=cache))
            await asyncio.sleep(.05)
            assert not finishing.done()
            await access.withdraw(db, world.actors['a'])
        await asyncio.wait_for(finishing, 3)
        final, _, messages = await world.inspect(database, queued.public_id)
        assert final.reason == 'access_revoked' and final.reserved == 0
        assert not any(message.role == 'assistant' for message in messages)
    world.run(action)
