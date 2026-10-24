"""RQ entry points; no keys or credentials are passed as job arguments."""
import asyncio
from uuid import uuid4

from redis import Redis
from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError
from sqlalchemy import select

from app.common.exceptions import BusinessException
from app.models.knowledge import KnowledgeVersion


async def enqueue_version(db, settings, version_id, connection: Redis):
    if not settings.configured:
        raise BusinessException("请先配置百炼嵌入 Key 和北京地域地址", code=503)
    row = await db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.id == version_id).with_for_update())
    if row is None:
        raise BusinessException("资料版本不存在", code=404)
    if row.job_id:
        try:
            job = Job.fetch(row.job_id, connection=connection)
            if job.get_status() in {"queued", "started", "deferred", "scheduled"}:
                await db.commit()
                return row.job_id
        except NoSuchJobError:
            pass
    job_id = uuid4().hex
    row.job_id, row.status, row.error = job_id, "queued", None
    await db.commit()
    try:
        Queue("knowledge", connection=connection).enqueue(
            ingest_job, version_id, job_id, job_id=job_id, job_timeout=900,
            result_ttl=3600, failure_ttl=3600)
    except Exception:
        row.status = "failed"
        row.error = "任务未能进入队列，请检查 Redis 后重试"
        await db.commit()
        raise BusinessException("知识入库队列暂不可用", code=503) from None
    return job_id


def ingest_job(version_id: int, job_id: str):
    async def run():
        from app.config import load_settings
        from app.database import Database
        from app.knowledge.settings import load_knowledge_settings
        from app.services.knowledge_service import embed_version
        database = Database(load_settings().database_url)
        try:
            return await embed_version(database, load_knowledge_settings(), version_id, job_id=job_id)
        finally:
            await database.dispose()
    try:
        return asyncio.run(run())
    except Exception:
        raise RuntimeError("知识入库失败；原有效索引保留，请检查资料任务状态") from None
