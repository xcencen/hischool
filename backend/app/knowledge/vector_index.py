"""Checksum-verified, rebuildable FAISS cosine indexes with atomic writes."""

from contextlib import suppress
from dataclasses import dataclass
import hashlib
import hmac
from numbers import Integral
import os
from pathlib import Path
import re
from typing import Sequence
import tempfile

import faiss
import numpy as np


class KnowledgeIndexError(RuntimeError):
    """An index or its inputs could not be safely used."""


@dataclass(frozen=True, slots=True)
class IndexArtifact:
    sha256: str
    count: int


@dataclass(frozen=True, slots=True)
class SearchMatch:
    chunk_id: int
    score: float


def _dimensions(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise KnowledgeIndexError("知识索引维度必须为正整数。")


def _chunk_ids(values: Sequence[int]) -> np.ndarray:
    try:
        ids = list(values)
        if any(
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, Integral)
            or not 0 < value <= np.iinfo(np.int64).max
            for value in ids
        ):
            raise ValueError
        normalized = [int(value) for value in ids]
        if len(set(normalized)) != len(normalized):
            raise ValueError
        return np.asarray(normalized, dtype=np.int64)
    except (ValueError, TypeError, OverflowError):
        raise KnowledgeIndexError("知识片段标识必须为唯一的正整数。") from None


def _normalized_vectors(vectors: object, dimensions: int) -> np.ndarray:
    try:
        raw = np.asarray(vectors)
        if raw.ndim == 1 and raw.size == 0:
            raw = np.empty((0, dimensions), dtype=np.float32)
        if raw.ndim != 2 or raw.shape[1] != dimensions or raw.dtype.kind not in "fiu":
            raise ValueError
        if any(isinstance(value, (bool, np.bool_)) for row in vectors for value in row):
            raise ValueError
        with np.errstate(over="ignore", invalid="ignore"):
            array = raw.astype(np.float32)
        if not np.isfinite(array).all():
            raise ValueError
        if not len(array):
            return np.ascontiguousarray(array)
        scale = np.max(np.abs(array), axis=1)
        if np.any(scale == 0):
            raise ValueError
        # Scaling in float64 avoids float32 overflow/underflow during L2 norms.
        scaled = array.astype(np.float64) / scale[:, None]
        norms = np.linalg.norm(scaled, axis=1)
        return np.ascontiguousarray((scaled / norms[:, None]).astype(np.float32))
    except (ValueError, TypeError, OverflowError):
        raise KnowledgeIndexError("知识向量必须具有正确维度，且为有限非零的 float32 数值。") from None


def write_index(
    path: Path,
    ids: Sequence[int],
    vectors: list[list[float]],
    dimensions: int = 1024,
) -> IndexArtifact:
    _dimensions(dimensions)
    chunk_ids = _chunk_ids(ids)
    normalized = _normalized_vectors(vectors, dimensions)
    if len(chunk_ids) != len(normalized):
        raise KnowledgeIndexError("知识片段标识与向量数量不一致。")
    temporary: Path | None = None
    try:
        target = Path(path)
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimensions))
        if len(chunk_ids):
            index.add_with_ids(normalized, chunk_ids)
        payload = faiss.serialize_index(index).tobytes()
        artifact = IndexArtifact(hashlib.sha256(payload).hexdigest(), len(chunk_ids))
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix="." + target.name + ".", suffix=".tmp", dir=target.parent, delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        return artifact
    except KnowledgeIndexError:
        raise
    except Exception:
        raise KnowledgeIndexError("知识索引写入失败，上一有效索引保持不变。") from None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def search_index(
    path: Path,
    expected_sha256: str,
    query: list[float],
    top_k: int,
    dimensions: int = 1024,
) -> list[SearchMatch]:
    _dimensions(dimensions)
    if type(top_k) is not int or top_k <= 0:
        raise KnowledgeIndexError("知识检索数量必须为正整数。")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise KnowledgeIndexError("知识索引校验信息无效。")
    try:
        raw_query = np.asarray(query)
        if raw_query.ndim != 1:
            raise KnowledgeIndexError("知识检索向量维度无效。")
        normalized_query = _normalized_vectors([query], dimensions)
        payload = Path(path).read_bytes()
        if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_sha256.lower()):
            raise KnowledgeIndexError("知识索引完整性校验失败。")
        # Validate against the trusted database checksum before native parsing.
        index = faiss.deserialize_index(np.frombuffer(payload, dtype=np.uint8))
        if (
            not isinstance(index, faiss.IndexIDMap2)
            or index.d != dimensions
            or index.metric_type != faiss.METRIC_INNER_PRODUCT
            or not isinstance(faiss.downcast_index(index.index), faiss.IndexFlatIP)
        ):
            raise KnowledgeIndexError("知识索引类型或维度不匹配。")
        stored_ids = faiss.vector_to_array(index.id_map)
        if len(_chunk_ids(stored_ids)) != index.ntotal:
            raise KnowledgeIndexError("知识索引片段标识无效。")
        if index.ntotal == 0:
            return []
        scores, ids = index.search(normalized_query, min(top_k, int(index.ntotal)))
        matches: list[SearchMatch] = []
        for chunk_id, score in zip(ids[0], scores[0], strict=True):
            if chunk_id <= 0 or not np.isfinite(score):
                raise KnowledgeIndexError("知识索引返回了无效结果。")
            matches.append(SearchMatch(int(chunk_id), max(-1.0, min(1.0, float(score)))))
        return matches
    except KnowledgeIndexError:
        raise
    except Exception:
        raise KnowledgeIndexError("知识索引无法读取，请重建索引后重试。") from None
