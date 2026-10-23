"""Explicit campus runtime; bootstrap never imports this module."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import load_settings
from app.database import Database


@asynccontextmanager
async def campus_lifespan(application: FastAPI):
    settings = load_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=3, socket_timeout=3,
    )
    application.state.settings = settings
    application.state.database = database
    application.state.redis = redis
    try:
        yield
    finally:
        await redis.aclose()
        await database.dispose()


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    async def database_ready() -> bool:
        async with request.app.state.database.session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True

    async def redis_ready() -> bool:
        return bool(await request.app.state.redis.ping())

    async def probe(check) -> bool:
        try:
            return bool(await asyncio.wait_for(check(), timeout=4))
        except Exception:
            # Never expose connection strings or credentials through errors.
            return False

    mysql, redis = await asyncio.gather(probe(database_ready), probe(redis_ready))
    code = 200 if mysql and redis else 503
    return JSONResponse(status_code=code, content={
        "code": code,
        "message": "ok" if code == 200 else "基础服务尚未就绪",
        "data": {"mysql": mysql, "redis": redis},
    })
