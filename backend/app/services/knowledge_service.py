"""Versioned ingestion and retrieval, independent of chat prompts or tools."""
import asyncio
import hashlib
from pathlib import Path
import re
from uuid import uuid4

import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.mysql import insert

from app.common.exceptions import BusinessException
from app.models.knowledge import (KnowledgeChunk, KnowledgeDocument, KnowledgeIndex, KnowledgePage,
                                 KnowledgeState, KnowledgeVersion)
from app.knowledge.documents import MAX_DOCUMENT_BYTES, parse_document
from app.knowledge.embeddings import BailianEmbeddingClient, EmbeddingUnavailable
from app.knowledge.settings import KnowledgeSettings
from app.knowledge.vector_index import KnowledgeIndexError, search_index, write_index


async def ensure_knowledge_state(session):
    statement = insert(KnowledgeState).values(id=1, active_index_id=None)
    await session.execute(statement.on_duplicate_key_update(id=KnowledgeState.id))


def storage_path(root: Path, key: str, *, index=False) -> Path:
    pattern = r"[0-9a-f]{32}\.index" if index else r"[0-9a-f]{64}\.(pdf|md|txt)"
    if not re.fullmatch(pattern, key):
        raise BusinessException("资料存储信息无效", code=503)
    path = (root/key).resolve()
    if not path.is_relative_to(root.resolve()):
        raise BusinessException("资料存储信息无效", code=503)
    return path


async def lock_state(db):
    row = await db.scalar(select(KnowledgeState).where(KnowledgeState.id == 1).with_for_update()
                           .execution_options(populate_existing=True))
    if row is None:
        raise BusinessException("知识库尚未初始化，请先执行迁移和种子", code=503)
    return row


async def import_document(db, settings: KnowledgeSettings, path: Path, *, code: str, title=None, category="regulations"):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", code) or category not in {"regulations", "guide", "faq"}:
        raise BusinessException("资料编码或分类无效", code=422)
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise BusinessException("资料文件超出大小限制", code=422)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    parsed = await asyncio.to_thread(parse_document, path, title=title)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise BusinessException("读取过程中原件发生变化，请重试导入", code=409)
    if not parsed.chunks:
        raise BusinessException("资料无可检索文本，图片附件需先识别", code=422)
    if len(parsed.title) > 150 or len(path.name) > 255 or len(parsed.chunks) > 10000:
        raise BusinessException("资料标题、文件名或片段数量超出限制", code=422)
    extension = {"pdf": "pdf", "markdown": "md", "text": "txt"}[parsed.source_type]
    key = digest+"."+extension
    settings.source_dir.mkdir(parents=True, exist_ok=True)
    target = storage_path(settings.source_dir, key)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise BusinessException("已保存原件校验失败", code=503)
    else:
        temporary = target.with_suffix(target.suffix+"."+uuid4().hex+".tmp")
        with temporary.open("xb") as saved:
            saved.write(raw)
            saved.flush()
            import os
            os.fsync(saved.fileno())
        temporary.replace(target)
    # Parsing and file I/O happen before the short serialization transaction.
    await lock_state(db)
    document = await db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.code == code).with_for_update())
    if document is None:
        document = KnowledgeDocument(code=code, title=parsed.title, category=category, active=1, latest_version=0)
        db.add(document)
        await db.flush()
    existing = await db.scalar(select(KnowledgeVersion).where(
        KnowledgeVersion.document_id == document.id, KnowledgeVersion.source_sha256 == digest).with_for_update())
    if existing is not None:
        await db.commit()
        return existing
    number = document.latest_version + 1
    version = KnowledgeVersion(document_id=document.id, version=number, title=parsed.title,
        source_sha256=digest, source_key=key, original_name=path.name, source_type=parsed.source_type,
        page_count=len(parsed.pages), chunk_count=len(parsed.chunks), warnings=parsed.warnings, status="parsed")
    db.add(version)
    await db.flush()
    pages = {}
    for page in parsed.pages:
        item = KnowledgePage(version_id=version.id, page_number=page.page_number, page_label=page.page_label,
                             content=page.text, needs_ocr=int(page.needs_ocr))
        db.add(item)
        pages[page.page_number] = item
    await db.flush()
    db.add_all([KnowledgeChunk(version_id=version.id, page_id=pages[chunk.page_number].id,
        ordinal=chunk.ordinal, chapter=(chunk.chapter or "正文")[:500], content=chunk.text,
        start_offset=chunk.start_offset, end_offset=chunk.end_offset) for chunk in parsed.chunks])
    document.latest_version = number
    await db.commit()
    return version


def embedding_client(settings):
    if not settings.configured:
        raise EmbeddingUnavailable("百炼嵌入服务未配置")
    return BailianEmbeddingClient(api_key=settings.api_key, base_url=settings.base_url,
                                  model=settings.model, dimensions=settings.dimensions)


async def embed_version(database, settings, version_id, *, embedder=None, job_id=None):
    try:
        client = embedder or embedding_client(settings)
        async with database.session_factory() as db:
            version = await db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.id == version_id).with_for_update())
            if version is None:
                raise BusinessException("资料版本不存在", code=404)
            if job_id is not None and version.job_id != job_id:
                raise BusinessException("导入任务已被替换", code=409)
            version.status, version.error = "processing", None
            await db.commit()
        while True:
            async with database.session_factory() as db:
                version = await db.get(KnowledgeVersion, version_id)
                if job_id is not None and version.job_id != job_id:
                    raise BusinessException("导入任务已被替换", code=409)
                batch = list((await db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == version_id,
                    or_(KnowledgeChunk.vector.is_(None), KnowledgeChunk.embedding_model.is_(None),
                        KnowledgeChunk.embedding_model != settings.model, KnowledgeChunk.embedding_dimension.is_(None),
                        KnowledgeChunk.embedding_dimension != settings.dimensions, KnowledgeChunk.provider_hash.is_(None),
                        KnowledgeChunk.provider_hash != settings.provider_hash))
                    .order_by(KnowledgeChunk.ordinal).limit(10))).all())
                if not batch:
                    break
                payloads = [chunk.content for chunk in batch]
                ids = [chunk.id for chunk in batch]
            vectors = await client.embed_texts(payloads)
            if len(vectors) != len(ids):
                raise EmbeddingUnavailable("嵌入结果数量无效")
            async with database.session_factory() as db:
                current = await db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.id == version_id).with_for_update())
                if job_id is not None and current.job_id != job_id:
                    raise BusinessException("导入任务已被替换", code=409)
                for chunk_id, vector in zip(ids, vectors):
                    array = np.asarray(vector, dtype="<f4")
                    if array.shape != (settings.dimensions,) or not np.isfinite(array).all() or np.linalg.norm(array) == 0:
                        raise EmbeddingUnavailable("嵌入结果格式无效")
                    chunk = await db.get(KnowledgeChunk, chunk_id)
                    chunk.vector = array.tobytes()
                    chunk.embedding_model, chunk.embedding_dimension = settings.model, settings.dimensions
                    chunk.provider_hash = settings.provider_hash
                await db.commit()
        async with database.session_factory() as db:
            current = await db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.id == version_id).with_for_update())
            if job_id is not None and current.job_id != job_id:
                raise BusinessException("导入任务已被替换", code=409)
            current.status = "embedded"
            await db.commit()
        return await rebuild_index(database, settings, candidate_version_id=version_id, candidate_job_id=job_id)
    except Exception:
        async with database.session_factory() as db:
            current = await db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.id == version_id).with_for_update())
            if current is not None and (job_id is None or current.job_id == job_id):
                current.status = "failed"
                current.error = "嵌入或索引构建失败，原有效索引保留；请检查配置后重试"
                await db.commit()
        raise


async def rebuild_index(database, settings, *, candidate_version_id=None, candidate_job_id=None):
    async with database.session_factory() as db:
        state = await lock_state(db)
        previous = await db.get(KnowledgeIndex, state.active_index_id) if state.active_index_id else None
        provider = settings.provider_hash if settings.base_url else previous.provider_hash if previous else settings.provider_hash
        documents = list((await db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.id)
                                           .with_for_update().execution_options(populate_existing=True))).all())
        selected, ids, vectors, versions = [], [], [], []
        for document in documents:
            if not document.active:
                continue
            candidate = None
            if candidate_version_id:
                candidate = await db.scalar(select(KnowledgeVersion).where(
                    KnowledgeVersion.id == candidate_version_id).with_for_update())
                if candidate is not None and candidate_job_id is not None and candidate.job_id != candidate_job_id:
                    raise BusinessException("导入任务已被替换", code=409)
                if candidate is not None and (candidate.document_id != document.id or (
                        document.active_version and candidate.version < document.active_version)):
                    candidate = None
            if candidate is None and document.active_version:
                candidate = await db.scalar(select(KnowledgeVersion).where(
                    KnowledgeVersion.document_id == document.id, KnowledgeVersion.version == document.active_version))
            if candidate is None:
                candidate = await db.scalar(select(KnowledgeVersion).where(
                    KnowledgeVersion.document_id == document.id, KnowledgeVersion.status.in_(["embedded", "indexed"]))
                    .order_by(KnowledgeVersion.version.desc()))
            if candidate is None:
                continue
            chunks = list((await db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == candidate.id)
                                            .order_by(KnowledgeChunk.id))).all())
            if not chunks or any(chunk.vector is None or chunk.embedding_model != settings.model
                or chunk.embedding_dimension != settings.dimensions or chunk.provider_hash != provider for chunk in chunks):
                if candidate_version_id == candidate.id:
                    raise BusinessException("资料向量尚未完整生成", code=409)
                raise BusinessException("现有向量与嵌入配置不一致，请重新嵌入", code=409)
            for chunk in chunks:
                array = np.frombuffer(chunk.vector, dtype="<f4")
                if array.shape != (settings.dimensions,) or not np.isfinite(array).all() or np.linalg.norm(array) == 0:
                    raise BusinessException("保存的向量校验失败", code=503)
                ids.append(chunk.id)
                vectors.append(array.tolist())
            selected.append((document, candidate))
            versions.append(candidate.id)
        if not vectors:
            raise BusinessException("没有可用于重建的已保存向量", code=409)
        version_name = uuid4().hex
        key = version_name+".index"
        settings.index_dir.mkdir(parents=True, exist_ok=True)
        artifact = await asyncio.to_thread(write_index, storage_path(settings.index_dir, key, index=True),
                                          ids, vectors, dimensions=settings.dimensions)
        index = KnowledgeIndex(version=version_name, file_key=key, sha256=artifact.sha256, model=settings.model,
            dimensions=settings.dimensions, provider_hash=provider, vector_count=artifact.count, version_ids=versions)
        db.add(index)
        await db.flush()
        for document, candidate in selected:
            document.active_version = candidate.version
            document.title = candidate.title
            candidate.status, candidate.error = "indexed", None
        state.active_index_id = index.id
        await db.commit()
        return index.version


async def set_active(db, document_id, active):
    await lock_state(db)
    document = await db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update())
    if document is None:
        raise BusinessException("资料不存在", code=404)
    document.active = int(active)
    await db.commit()


async def active_index(db):
    state = await db.scalar(select(KnowledgeState).where(KnowledgeState.id == 1)
                            .execution_options(populate_existing=True))
    return await db.get(KnowledgeIndex, state.active_index_id) if state and state.active_index_id else None


def visible_chunk_query():
    return (select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument, KnowledgePage)
        .join(KnowledgeVersion, KnowledgeVersion.id == KnowledgeChunk.version_id)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
        .join(KnowledgePage, KnowledgePage.id == KnowledgeChunk.page_id)
        .where(KnowledgeDocument.active == 1, KnowledgeDocument.active_version == KnowledgeVersion.version))


async def status(db, settings):
    index = await active_index(db)
    document_count = await db.scalar(select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.active == 1))
    chunks = await db.scalar(select(func.count()).select_from(KnowledgeChunk).join(
        KnowledgeVersion, KnowledgeVersion.id == KnowledgeChunk.version_id).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id).where(
        KnowledgeDocument.active == 1, KnowledgeDocument.latest_version == KnowledgeVersion.version))
    eligible = await db.scalar(select(func.count()).select_from(visible_chunk_query().where(
        KnowledgeVersion.id.in_(index.version_ids if index else [])).subquery()))
    compatible = bool(index and index.model == settings.model and index.dimensions == settings.dimensions
                      and (not settings.base_url or index.provider_hash == settings.provider_hash))
    ready = bool(compatible and eligible)
    message = "知识检索已就绪" if ready and settings.configured else "请先配置百炼文本嵌入服务" if not settings.configured else "资料尚未完成嵌入和索引构建"
    return dict(configured=settings.configured, ready=ready, model=settings.model, dimensions=settings.dimensions,
                document_count=document_count or 0, chunk_count=chunks or 0,
                index_version=index.version if index else None, message=message)


async def documents(db):
    docs = (await db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.active == 1)
                             .order_by(KnowledgeDocument.id))).all()
    result = []
    for doc in docs:
        version = await db.scalar(select(KnowledgeVersion).where(
            KnowledgeVersion.document_id == doc.id, KnowledgeVersion.version == (doc.active_version or doc.latest_version)))
        if version:
            result.append(dict(id=doc.id, title=version.title, category=doc.category, version=version.version,
                page_count=version.page_count, chunk_count=version.chunk_count,
                status="ready" if doc.active_version == version.version else version.status, warnings=version.warnings))
    return result


async def source(db, settings, document_id, version_number):
    await db.commit()
    row = (await db.execute(select(KnowledgeVersion, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id).where(
        KnowledgeDocument.id == document_id, KnowledgeDocument.active == 1,
        KnowledgeVersion.version == version_number))).first()
    if row is None:
        raise BusinessException("原文不存在或资料已停用", code=404)
    version, document = row
    path = storage_path(settings.source_dir, version.source_key)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != version.source_sha256:
        raise BusinessException("原文缺失或校验失败", code=503)
    mime = {"pdf": "application/pdf", "markdown": "text/markdown", "text": "text/plain"}[version.source_type]
    return path, mime, version.original_name


async def search(db, settings, query, top_k, *, embedder=None):
    # The authentication dependency may already have opened a MySQL read snapshot.
    await db.commit()
    initial = await status(db, settings)
    if not initial["ready"]:
        raise BusinessException(initial["message"], code=503)
    if embedder is None and not settings.configured:
        raise BusinessException("百炼文本嵌入服务未配置", code=503)
    try:
        vectors = await (embedder or embedding_client(settings)).embed_texts([query])
    except EmbeddingUnavailable:
        raise BusinessException("百炼文本嵌入服务暂不可用，请检查配置后重试", code=503) from None
    await db.commit()
    index = await active_index(db)
    if index is None or index.model != settings.model or index.dimensions != settings.dimensions or (
            settings.base_url and index.provider_hash != settings.provider_hash):
        raise BusinessException("索引与当前嵌入配置不一致", code=503)
    try:
        hits = await asyncio.to_thread(search_index, storage_path(settings.index_dir, index.file_key, index=True),
            index.sha256, vectors[0], top_k=index.vector_count, dimensions=settings.dimensions)
    except KnowledgeIndexError:
        raise BusinessException("知识索引校验失败，请从保存的向量重建", code=503) from None
    # Re-open the read view after the network/file awaits. A completed disable
    # must be visible even if the request started before that change.
    await db.commit()
    scores = {hit.chunk_id: float(hit.score) for hit in hits if hit.score >= settings.min_score}
    rows = (await db.execute(visible_chunk_query().where(
        KnowledgeChunk.id.in_(list(scores)), KnowledgeVersion.id.in_(index.version_ids)))).all() if scores else []
    results = []
    for chunk, version, document, page in sorted(rows, key=lambda row: scores[row[0].id], reverse=True)[:top_k]:
        results.append(dict(chunk_id=chunk.id, document_id=document.id, document_title=version.title,
            version=version.version, chapter=chunk.chapter, page_number=page.page_number,
            page_label=page.page_label, content=chunk.content, score=max(-1.0, min(1.0, scores[chunk.id]))))
    return dict(query=query, index_version=index.version, results=results, insufficient=not bool(results),
                message="以下为资料原文片段，请结合出处阅读。" if results else "资料中未检索到足够相关内容，请补充问题或资料。")
