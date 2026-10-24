"""Embedding protocol and durable FAISS behavior without any real model calls."""

import asyncio
import hashlib
import json
import traceback

import faiss
import httpx
import numpy as np
import pytest

from app.knowledge import embeddings, vector_index
from app.knowledge.embeddings import BailianEmbeddingClient, EmbeddingUnavailable
from app.knowledge.vector_index import KnowledgeIndexError, search_index, write_index


DIMENSIONS = 1024
KEY = "unit-test-embedding-key"
BASE = "https://embedding.invalid/compatible-mode/v1"


def vector(first=1.0, second=0.0):
    return [first, second, *([0.0] * (DIMENSIONS - 2))]


def embedding_response(count=1):
    return {"model": "text-embedding-v4", "data": [
        {"index": index, "embedding": vector(index + 1.0, 1.0)} for index in range(count)
    ]}


def response(payload, status=200):
    return httpx.Response(status, content=json.dumps(payload).encode(),
                          headers={"content-type": "application/json"})


def client(handler):
    return BailianEmbeddingClient(KEY, BASE, transport=httpx.MockTransport(handler))


def test_embedding_batches_and_restores_response_order():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert str(request.url) == BASE + "/embeddings"
        assert request.headers["Authorization"] == "Bearer " + KEY
        assert body["model"] == "text-embedding-v4"
        assert body["dimensions"] == DIMENSIONS
        assert body["encoding_format"] == "float"
        assert request.extensions["timeout"]["read"] == 30
        data = [{"index": position, "embedding": vector(float(text.split("-")[1]) + 1)}
                for position, text in enumerate(body["input"])]
        return response({"data": list(reversed(data))})

    result = asyncio.run(client(handler).embed_texts([f"text-{index}" for index in range(23)]))
    assert [len(item["input"]) for item in requests] == [10, 10, 3]
    assert [item[0] for item in result] == list(range(1, 24))
    assert all(len(item) == DIMENSIONS for item in result)


def test_empty_embedding_batch_never_calls_upstream():
    def forbid(_):
        raise AssertionError("Empty batches must not call a model")
    assert asyncio.run(client(forbid).embed_texts([])) == []


@pytest.mark.parametrize("texts", [None, "text", [None], [""], ["   "]])
def test_embedding_rejects_invalid_texts_without_upstream(texts):
    def forbid(_):
        raise AssertionError("Invalid inputs must not call a model")
    with pytest.raises(EmbeddingUnavailable):
        asyncio.run(client(forbid).embed_texts(texts))


@pytest.mark.parametrize("key,base,options", [
    ("", BASE, {}), (" ", BASE, {}), (None, BASE, {}), ("bad\nkey", BASE, {}),
    (KEY, "", {}), (KEY, None, {}), (KEY, "not-an-address", {}),
    (KEY, "https://name:private@embedding.invalid/v1", {}),
    (KEY, BASE + "?key=private", {}), (KEY, BASE + "#private", {}),
    (KEY, BASE, {"model": "another-model"}), (KEY, BASE, {"dimensions": 768}),
    (KEY, BASE, {"dimensions": True}), (KEY, BASE, {"timeout_s": 0}),
    (KEY, BASE, {"timeout_s": float("nan")}),
])
def test_embedding_configuration_is_explicit_and_fixed(key, base, options):
    with pytest.raises(EmbeddingUnavailable) as error:
        BailianEmbeddingClient(key, base, **options)
    assert KEY not in str(error.value)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("kind", [
    "not-object", "missing-data", "not-list", "missing-record", "duplicate-index",
    "negative-index", "noninteger-index", "boolean-index", "bad-dimension",
    "zero-vector", "nan-vector", "infinite-vector", "boolean-value", "string-value", "wrong-model",
])
def test_embedding_rejects_incomplete_or_invalid_vectors(kind):
    payload = embedding_response(2)
    if kind == "not-object": payload = []
    elif kind == "missing-data": payload = {}
    elif kind == "not-list": payload["data"] = "private-upstream-body"
    elif kind == "missing-record": payload["data"].pop()
    elif kind == "duplicate-index": payload["data"][1]["index"] = 0
    elif kind == "negative-index": payload["data"][0]["index"] = -1
    elif kind == "noninteger-index": payload["data"][0]["index"] = 0.0
    elif kind == "boolean-index": payload["data"][0]["index"] = False
    elif kind == "bad-dimension": payload["data"][0]["embedding"].pop()
    elif kind == "zero-vector": payload["data"][0]["embedding"] = [0.0] * DIMENSIONS
    elif kind == "nan-vector": payload["data"][0]["embedding"][0] = float("nan")
    elif kind == "infinite-vector": payload["data"][0]["embedding"][0] = float("inf")
    elif kind == "boolean-value": payload["data"][0]["embedding"][0] = True
    elif kind == "string-value": payload["data"][0]["embedding"][0] = "1.0"
    elif kind == "wrong-model": payload["model"] = "another-model"
    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(lambda _: response(payload)).embed_texts(["text-a", "text-b"]))
    assert KEY not in str(error.value)
    assert "private-upstream-body" not in str(error.value)


def test_embedding_rate_limit_and_server_error_retry_are_bounded(monkeypatch):
    statuses = [429, 503, 200]
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    def handler(_):
        return response(embedding_response(), statuses.pop(0))

    monkeypatch.setattr(embeddings.asyncio, "sleep", sleep)
    assert len(asyncio.run(client(handler).embed_texts(["text"]))) == 1
    assert statuses == []
    assert delays == [0.25, 0.5]


@pytest.mark.parametrize("status,expected_calls", [(429, 3), (500, 3), (401, 1), (400, 1), (302, 1)])
def test_embedding_request_failure_is_sanitized_without_fallback(monkeypatch, status, expected_calls):
    calls = []

    async def sleep(_):
        return None

    def handler(request):
        calls.append(request)
        return response({"error": "private-upstream-body " + KEY}, status)

    monkeypatch.setattr(embeddings.asyncio, "sleep", sleep)
    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler).embed_texts(["text"]))
    assert len(calls) == expected_calls
    printable = "".join(traceback.format_exception(error.value))
    assert KEY not in printable
    assert "private-upstream-body" not in printable


def test_embedding_transport_failure_does_not_expose_credentials():
    def fail(request):
        raise httpx.ConnectError("private-upstream-body " + KEY, request=request)
    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(fail).embed_texts(["text"]))
    assert KEY not in str(error.value)
    assert "private-upstream-body" not in str(error.value)


def test_embedding_later_batch_failure_returns_no_partial_vectors(monkeypatch):
    batches = []

    async def sleep(_):
        return None

    def handler(request):
        batch = json.loads(request.content)["input"]
        batches.append(batch)
        return response(embedding_response(len(batch)), 200 if len(batch) == 10 else 503)

    monkeypatch.setattr(embeddings.asyncio, "sleep", sleep)
    with pytest.raises(EmbeddingUnavailable):
        asyncio.run(client(handler).embed_texts(["text"] * 11))
    assert [len(batch) for batch in batches] == [10, 1, 1, 1]


def test_faiss_unicode_path_cosine_ranking_and_query_normalization(tmp_path):
    path = tmp_path / "校园知识" / "学生手册索引.faiss"
    artifact = write_index(path, [101, 203, 305], [vector(2), vector(0, 5), vector(-4)])
    assert artifact.count == 3
    assert artifact.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    matches = search_index(path, artifact.sha256, vector(50), 20)
    assert [match.chunk_id for match in matches] == [101, 203, 305]
    assert [match.score for match in matches] == pytest.approx([1, 0, -1])
    assert search_index(path, artifact.sha256.upper(), vector(), 1)[0].chunk_id == 101


def test_faiss_document_magnitude_cannot_change_cosine_ranking(tmp_path):
    path = tmp_path / "normalized.faiss"
    artifact = write_index(path, [1, 2], [vector(1000, 1000), vector()])
    matches = search_index(path, artifact.sha256, vector(), 2)
    assert [match.chunk_id for match in matches] == [2, 1]
    assert matches[1].score == pytest.approx(2 ** -0.5, abs=1e-6)


def test_faiss_normalization_handles_large_finite_float32_values(tmp_path):
    path = tmp_path / "large.faiss"
    artifact = write_index(path, [np.int64(1)], [vector(1e38, 1e38)])
    matches = search_index(path, artifact.sha256, vector(1e38, 1e38), 1)
    assert matches[0].score == pytest.approx(1, abs=1e-6)


def test_empty_faiss_index_is_a_valid_artifact(tmp_path):
    path = tmp_path / "empty.faiss"
    artifact = write_index(path, [], [])
    assert artifact.count == 0
    assert search_index(path, artifact.sha256, vector(), 5) == []


@pytest.mark.parametrize("ids", [[0], [-1], [True], [1.0], [2**63], [1, 1]])
def test_faiss_rejects_invalid_or_duplicate_chunk_ids(tmp_path, ids):
    with pytest.raises(KnowledgeIndexError):
        write_index(tmp_path / "invalid.faiss", ids, [vector() for _ in ids])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad_vector", [
    [1.0] * (DIMENSIONS - 1), [0.0] * DIMENSIONS,
    vector(float("nan")), vector(float("inf")), vector(1e100), vector(1e-60),
    vector("1.0"), vector(True), vector(np.bool_(True)), [True] * DIMENSIONS,
])
def test_faiss_rejects_invalid_vectors_before_writing(tmp_path, bad_vector):
    with pytest.raises(KnowledgeIndexError):
        write_index(tmp_path / "invalid.faiss", [1], [bad_vector])
    assert list(tmp_path.iterdir()) == []


def test_faiss_rejects_id_vector_count_mismatch(tmp_path):
    with pytest.raises(KnowledgeIndexError):
        write_index(tmp_path / "invalid.faiss", [1, 2], [vector()])


def test_faiss_invalid_replacement_keeps_the_existing_artifact(tmp_path):
    path = tmp_path / "index.faiss"
    original = write_index(path, [1], [vector()])
    with pytest.raises(KnowledgeIndexError):
        write_index(path, [2], [[0.0] * DIMENSIONS])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original.sha256
    assert search_index(path, original.sha256, vector(), 1)[0].chunk_id == 1


@pytest.mark.parametrize("dimensions", [0, -1, True, 1024.0])
def test_faiss_rejects_invalid_dimension_configuration(tmp_path, dimensions):
    with pytest.raises(KnowledgeIndexError):
        write_index(tmp_path / "invalid.faiss", [], [], dimensions=dimensions)


def test_faiss_checksum_is_checked_before_native_deserialization(tmp_path, monkeypatch):
    path = tmp_path / "modified.faiss"
    artifact = write_index(path, [1], [vector()])
    path.write_bytes(b"corrupted file")

    def forbid(_):
        raise AssertionError("Unchecked bytes reached native deserialization")

    monkeypatch.setattr(vector_index.faiss, "deserialize_index", forbid)
    with pytest.raises(KnowledgeIndexError, match="完整性"):
        search_index(path, artifact.sha256, vector(), 1)


def test_faiss_invalid_binary_with_matching_hash_is_rejected(tmp_path):
    path = tmp_path / "broken.faiss"
    contents = b"This is not a FAISS index"
    path.write_bytes(contents)
    with pytest.raises(KnowledgeIndexError):
        search_index(path, hashlib.sha256(contents).hexdigest(), vector(), 1)


def test_faiss_rejects_valid_file_with_wrong_dimensions_or_algorithm(tmp_path):
    path = tmp_path / "small.faiss"
    artifact = write_index(path, [1], [[1.0, 0.0]], dimensions=2)
    with pytest.raises(KnowledgeIndexError, match="维度"):
        search_index(path, artifact.sha256, vector(), 1)
    unsupported = faiss.IndexIDMap2(faiss.IndexFlatL2(DIMENSIONS))
    payload = faiss.serialize_index(unsupported).tobytes()
    path.write_bytes(payload)
    with pytest.raises(KnowledgeIndexError, match="类型"):
        search_index(path, hashlib.sha256(payload).hexdigest(), vector(), 1)


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5])
def test_faiss_rejects_invalid_result_limits(tmp_path, top_k):
    path = tmp_path / "index.faiss"
    artifact = write_index(path, [1], [vector()])
    with pytest.raises(KnowledgeIndexError):
        search_index(path, artifact.sha256, vector(), top_k)


@pytest.mark.parametrize("fault", ["replace", "fsync"])
def test_faiss_failed_publication_preserves_previous_file_and_cleans_temp(tmp_path, monkeypatch, fault):
    path = tmp_path / "旧索引.faiss"
    original = write_index(path, [1], [vector()])
    previous_bytes = path.read_bytes()

    def fail(*args):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(vector_index.os, fault, fail)
    with pytest.raises(KnowledgeIndexError) as error:
        write_index(path, [2], [vector(0, 1)])
    assert "private filesystem detail" not in str(error.value)
    assert path.read_bytes() == previous_bytes
    assert list(tmp_path.iterdir()) == [path]
    assert search_index(path, original.sha256, vector(), 1)[0].chunk_id == 1
