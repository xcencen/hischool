"""Run against the application packaged INSIDE the previous verified image."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from app.config import load_settings
from app.database import Database
from app.main import create_app
from app.models.assistant import Conversation
from app.utils.jwt import create_access_token

settings = load_settings()
url = make_url(settings.database_url)
assert url.host == 'test-mysql' and url.database == 'my_campus_test'
async def inspect_state():
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as db:
            conversation = await db.scalar(select(Conversation).order_by(Conversation.id))
            assert conversation is not None
            result = {}
            for name in ('assistant_runs','assistant_usage','assistant_budgets','assistant_alerts'):
                rows = (await db.execute(text('SELECT * FROM ' + name))).mappings().all()
                encoded = sorted(json.dumps(dict(row), sort_keys=True, default=str) for row in rows)
                result[name] = hashlib.sha256('\n'.join(encoded).encode()).hexdigest()
            return conversation.public_id, conversation.owner_id, result
    finally:
        await database.dispose()

identifier, owner, before = asyncio.run(inspect_state())
token = create_access_token(owner, 0, settings)
with TestClient(create_app(mode='campus')) as client:
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/ready').status_code == 200
    response = client.post('/api/assistant/conversations/'+identifier+'/runs',
        headers={'Authorization':'Bearer '+token}, json={'content':'Synthetic rollback','request_key':'old-image-closed'})
    assert response.status_code == 503
assert asyncio.run(inspect_state())[2] == before
print(json.dumps({'old_image_campus_http':200,'old_image_new_run_http':503,'financial_hashes_unchanged':True}))
