"""Pilot HTTP boundary uses real isolated storage and normal campus JWTs."""
from uuid import uuid4
import os
import pytest
from test_assistant_sessions_integration import client, world
from app.assistant import access

pytestmark = pytest.mark.skipif(os.environ.get('CAMPUS_ASSISTANT_INTEGRATION') != '1', reason='Requires isolated assistant MySQL/Redis')


def test_pilot_api_is_admin_scoped_strict_and_consent_is_versioned(client, world):
    version = 'http-' + uuid4().hex
    async def publish(db):
        await access.publish_policy(db, version, 'Synthetic notice', 'Synthetic only.')
    world.run(publish)
    student, admin = world.headers['a'], world.headers['b']
    url = '/api/admin/assistant/access/' + str(world.actors['a'].id)
    assert client.get('/api/admin/assistant/access', headers=student).status_code == 403
    assert client.put(url, headers=student, json={'eligible': True, 'expected_generation': 0}).status_code == 403
    assert client.put(url, headers=admin, json={'eligible': 'true', 'expected_generation': 0}).status_code == 422
    assert client.put(url, headers=admin, json={'eligible': True, 'expected_generation': 0, 'role': 'admin'}).status_code == 422
    denied = client.get('/api/assistant/access', headers=student).json()['data']
    assert not denied['eligible'] and not denied['can_run']
    assert client.post('/api/assistant/consent', headers=student, json={'policy_version': version}).status_code == 403
    grant = client.put(url, headers=admin, json={'eligible': True, 'expected_generation': 0})
    assert grant.status_code == 200 and grant.json()['data']['generation'] == 1
    assert client.put(url, headers=admin, json={'eligible': False, 'expected_generation': 0}).status_code == 409
    assert client.post('/api/assistant/consent', headers=student, json={'policy_version': 'old'}).status_code == 409
    confirmed = client.post('/api/assistant/consent', headers=student, json={'policy_version': version})
    assert confirmed.status_code == 200 and confirmed.json()['data']['consented']
    assert not confirmed.json()['data']['can_run']  # Both production switches stay closed.
    withdrawn = client.delete('/api/assistant/consent', headers=student)
    assert withdrawn.status_code == 200 and not withdrawn.json()['data']['consented']
    assert withdrawn.json()['data']['generation'] == 2
    assert client.get('/api/user/me', headers=student).status_code != 401
