"""Private MCP-owned resources, opened only by an explicit service lifespan."""

from dataclasses import dataclass
import os

from redis.asyncio import Redis

from app.config import _validate_redis_url, validate_database_url
from app.database import Database
from app.knowledge.settings import load_knowledge_settings


@dataclass
class MCPResources:
    database: Database
    redis: Redis
    knowledge_settings: object
    embedder: object = None

    async def close(self):
        try:
            await self.redis.aclose()
        finally:
            await self.database.dispose()


def create_resources(environ=None):
    source = os.environ if environ is None else environ
    database_url, redis_url = source.get("CAMPUS_DATABASE_URL", ""), source.get("CAMPUS_REDIS_URL", "")
    validate_database_url(database_url)
    _validate_redis_url(redis_url)
    try:
        knowledge = load_knowledge_settings(source)
    except (ValueError, TypeError):
        knowledge = None
    return MCPResources(Database(database_url), Redis.from_url(redis_url,
        decode_responses=True, socket_connect_timeout=3, socket_timeout=3), knowledge)
