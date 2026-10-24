"""Operator-only document import and index lifecycle; no hidden .env loading."""
import argparse
import asyncio
import json
from pathlib import Path

from redis import Redis
from sqlalchemy import select

from app.common.exceptions import BusinessException
from app.config import load_settings
from app.database import Database
from app.knowledge.embeddings import EmbeddingUnavailable
from app.knowledge.settings import load_knowledge_settings
from app.knowledge.tasks import enqueue_version
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion
from app.services import knowledge_service as service


async def execute(options):
    knowledge = load_knowledge_settings()
    if options.command == "probe":
        result = dict(key_loaded=bool(knowledge.api_key), configured=knowledge.configured,
            endpoint_configured=bool(knowledge.base_url), model=knowledge.model,
            dimensions=knowledge.dimensions)
        if options.live:
            if not knowledge.configured:
                raise BusinessException("请先配置百炼嵌入 Key 和北京地域地址", code=503)
            vectors = await service.embedding_client(knowledge).embed_texts(["校园知识库连通性验证"])
            if (not isinstance(vectors, list) or len(vectors) != 1
                    or not isinstance(vectors[0], list) or len(vectors[0]) != knowledge.dimensions):
                raise EmbeddingUnavailable("嵌入结果格式无效", reason="invalid_response")
            result["connectivity"] = True
        print(json.dumps(result, ensure_ascii=False))
        return
    runtime = load_settings()
    database = Database(runtime.database_url)
    try:
        async with database.session_factory() as db:
            if options.command == "import":
                version = await service.import_document(db, knowledge, Path(options.path),
                    code=options.code, title=options.title, category=options.category)
                print(json.dumps(dict(document_id=version.document_id, version_id=version.id,
                    version=version.version, status=version.status, pages=version.page_count,
                    chunks=version.chunk_count, warnings=version.warnings), ensure_ascii=False))
                if options.enqueue:
                    connection = Redis.from_url(runtime.redis_url)
                    try:
                        print("Queued task: " + await enqueue_version(db, knowledge, version.id, connection))
                    finally:
                        connection.close()
            elif options.command == "enqueue":
                connection = Redis.from_url(runtime.redis_url)
                try:
                    print("Queued task: " + await enqueue_version(db, knowledge, options.version_id, connection))
                finally:
                    connection.close()
            elif options.command == "build":
                print("Activated index: " + await service.embed_version(database, knowledge, options.version_id))
            elif options.command == "rebuild":
                print("Activated rebuilt index: " + await service.rebuild_index(database, knowledge))
            elif options.command == "set-active":
                await service.set_active(db, options.document_id, options.active)
                if options.active:
                    print("Document enabled; activate its saved vectors with the rebuild command.")
                else:
                    print("Document disabled; search and source access filter it immediately.")
            elif options.command == "inspect":
                print(json.dumps(await service.status(db, knowledge), ensure_ascii=False))
                versions = (await db.execute(select(KnowledgeVersion, KnowledgeDocument.code).join(
                    KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
                    .order_by(KnowledgeVersion.document_id, KnowledgeVersion.version))).all()
                for row, code in versions:
                    print(json.dumps(dict(code=code, document_id=row.document_id, version_id=row.id,
                        version=row.version, status=row.status, job_id=row.job_id, error=row.error,
                        pages=row.page_count, chunks=row.chunk_count), ensure_ascii=False))
    finally:
        await database.dispose()


def main():
    from app.knowledge.logging import configure_knowledge_logging

    parser = argparse.ArgumentParser(description="my-campus knowledge operator commands")
    commands = parser.add_subparsers(dest="command", required=True)
    importing = commands.add_parser("import")
    importing.add_argument("path")
    importing.add_argument("--code", required=True)
    importing.add_argument("--title")
    importing.add_argument("--category", choices=["faq", "regulations", "guide"], default="regulations")
    importing.add_argument("--enqueue", action="store_true")
    for name in ("enqueue", "build"):
        command = commands.add_parser(name)
        command.add_argument("version_id", type=int)
    commands.add_parser("rebuild")
    commands.add_parser("inspect")
    probing = commands.add_parser("probe", help="Check configuration without database or Redis access")
    probing.add_argument("--live", action="store_true", help="Send one short embedding request")
    switching = commands.add_parser("set-active")
    switching.add_argument("document_id", type=int)
    switching.add_argument("active", type=int, choices=[0, 1])
    options = parser.parse_args()
    configure_knowledge_logging()
    try:
        asyncio.run(execute(options))
    except BusinessException as error:
        raise SystemExit(error.message) from None
    except EmbeddingUnavailable as error:
        raise SystemExit(service.embedding_failure_message(error)) from None
    except Exception:
        raise SystemExit("Knowledge operation failed; check configuration, source and service availability locally.") from None


if __name__ == "__main__":
    main()
