"""Provider failures stay actionable, bounded and free of private request data."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import logging
import re
import traceback

import httpx
import pytest

from app.knowledge import embeddings
from app.knowledge.embeddings import BailianEmbeddingClient, EmbeddingUnavailable


KEY = "private-test-api-key-never-log"
BASE = "https://private-provider.invalid/compatible-mode/v1"
TEXT = "private-input-never-log"
BODY = "private-response-never-log"


@pytest.fixture(autouse=True)
def capture_embedding_module_logs(caplog):
    logger = logging.getLogger(embeddings.__name__)
    previous_propagation = logger.propagate
    already_attached = caplog.handler in logger.handlers
    if not already_attached:
        logger.addHandler(caplog.handler)
    logger.propagate = False
    try:
        yield
    finally:
        if not already_attached:
            logger.removeHandler(caplog.handler)
        logger.propagate = previous_propagation


def response(status=200, *, headers=None):
    payload = {"data": [{"index": 0, "embedding": [1.0] + [0.0] * 1023}]}
    if status != 200:
        payload = {"error": BODY + KEY + TEXT}
    return httpx.Response(status, json=payload, headers=headers)


def client(handler, **options):
    return BailianEmbeddingClient(KEY, BASE, transport=httpx.MockTransport(handler), **options)


@pytest.mark.parametrize("reason", [None, "private-unknown", [], 123])
def test_unknown_error_reasons_are_controlled_and_message_constructor_stays_compatible(reason):
    failure = EmbeddingUnavailable("legacy message", reason=reason)
    assert str(failure) == "legacy message"
    assert failure.reason == "unavailable"


@pytest.mark.parametrize("total_timeout", [0, -1, True, float("nan"), float("inf"), "45"])
def test_total_timeout_requires_a_positive_finite_number(total_timeout):
    with pytest.raises(EmbeddingUnavailable) as error:
        client(lambda _: response(), total_timeout_s=total_timeout)
    assert error.value.reason == "configuration"


@pytest.mark.parametrize("status", [401, 403])
def test_provider_authentication_failure_is_not_retried(status, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return response(status)

    caplog.set_level(logging.INFO, logger=embeddings.__name__)
    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler).embed_texts([TEXT]))
    assert len(calls) == 1 and error.value.reason == "authentication"
    assert "鉴权失败" in str(error.value)
    assert "reason=authentication" in caplog.text
    assert_private_data_absent(error.value, caplog.text)


@pytest.mark.parametrize("status,reason,calls", [
    (429, "rate_limited", 3), (500, "upstream", 3),
    (503, "upstream", 3), (504, "timeout", 3),
    (400, "invalid_request", 1), (408, "timeout", 1),
    (302, "invalid_response", 1),
])
def test_http_error_categories_and_retry_limits(status, reason, calls, monkeypatch, caplog):
    requests, delays = [], []

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        requests.append(request)
        return response(status)

    monkeypatch.setattr(embeddings.asyncio, "sleep", sleep)
    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler).embed_texts([TEXT]))
    assert error.value.reason == reason and len(requests) == calls
    assert delays == ([0.25, 0.5] if calls == 3 else [])
    assert_private_data_absent(error.value, caplog.text)


@pytest.mark.parametrize("value,expected", [
    ("2", 2), ("0", 0), ("100000", 5), ("-1", 0.25),
    ("nan", 0.25), ("inf", 0.25), ("nonsense", 0.25),
    ("", 0.25),
    (format_datetime(datetime(2100, 1, 1, tzinfo=timezone.utc), usegmt=True), 5),
    (format_datetime(datetime(2000, 1, 1, tzinfo=timezone.utc), usegmt=True), 0),
])
def test_retry_after_is_bounded_or_uses_fallback(value, expected, monkeypatch):
    delays, requests = [], []

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        requests.append(request)
        return response(429, headers={"Retry-After": value}) if len(requests) == 1 else response()

    monkeypatch.setattr(embeddings.asyncio, "sleep", sleep)
    result = asyncio.run(client(handler).embed_texts([TEXT]))
    assert len(result) == 1 and len(requests) == 2 and delays == [expected]


def test_retry_after_http_date_uses_remaining_time(monkeypatch):
    delays, requests = [], []
    future = datetime.now(timezone.utc) + timedelta(seconds=3)

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        requests.append(request)
        return response(429, headers={"Retry-After": format_datetime(future, usegmt=True)}) if len(requests) == 1 else response()

    monkeypatch.setattr(embeddings.asyncio, "sleep", sleep)
    assert len(asyncio.run(client(handler).embed_texts([TEXT]))) == 1
    assert len(delays) == 1 and 0 <= delays[0] <= 3


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_transport_timeouts_have_safe_category_without_unbounded_retry(failure, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        raise failure(BODY + KEY, request=request)

    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler).embed_texts([TEXT]))
    assert len(calls) == 1 and error.value.reason == "timeout"
    assert_private_data_absent(error.value, caplog.text)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.RemoteProtocolError])
def test_transport_network_errors_are_sanitized(failure, caplog):
    def handler(request):
        raise failure(BODY + KEY, request=request)

    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler).embed_texts([TEXT]))
    assert error.value.reason == "network"
    assert_private_data_absent(error.value, caplog.text)


def test_total_timeout_bounds_network_wait_and_records_safe_reason(caplog):
    cancelled = []

    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler, total_timeout_s=0.02).embed_texts([TEXT]))
    assert cancelled == [True] and error.value.reason == "timeout"
    assert "reason=timeout" in caplog.text
    assert_private_data_absent(error.value, caplog.text)


def test_total_timeout_also_bounds_retry_after_wait():
    requests = []

    def handler(request):
        requests.append(request)
        return response(429, headers={"Retry-After": "5"})

    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler, total_timeout_s=0.02).embed_texts([TEXT]))
    assert len(requests) == 1 and error.value.reason == "timeout"


def test_explicit_cancellation_propagates_without_provider_failure_log(caplog):
    async def run():
        started = asyncio.Event()

        async def handler(request):
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(client(handler).embed_texts([TEXT]))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert "outcome=failed" not in caplog.text


@pytest.mark.parametrize("kind", ["json", "vector"])
def test_invalid_provider_response_is_actionable_without_private_body(kind, caplog):
    def handler(request):
        if kind == "json":
            return httpx.Response(200, content=(BODY + KEY).encode())
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [KEY]}]})

    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler).embed_texts([TEXT]))
    assert error.value.reason == "invalid_response"
    assert_private_data_absent(error.value, caplog.text)


def test_unexpected_exception_does_not_escape_through_message_or_logs(caplog):
    def handler(request):
        raise RuntimeError(KEY + BODY + TEXT)

    with pytest.raises(EmbeddingUnavailable) as error:
        asyncio.run(client(handler).embed_texts([TEXT]))
    assert error.value.reason == "unavailable"
    assert_private_data_absent(error.value, caplog.text)


def test_success_log_contains_only_controlled_operational_metadata(caplog):
    caplog.set_level(logging.INFO, logger=embeddings.__name__)
    assert len(asyncio.run(client(lambda _: response()).embed_texts([TEXT]))) == 1
    records = [record for record in caplog.records if record.name == embeddings.__name__]
    assert len(records) == 1 and records[0].levelno == logging.INFO
    message = records[0].getMessage()
    assert re.search(r"request_id=[0-9a-f]{32}", message)
    assert "outcome=success" in message and "status=200" in message
    assert "attempt=1" in message and "batch_size=1" in message
    assert re.search(r"elapsed_ms=\d+", message)
    assert "reason=none" in message
    assert_private_data_absent(None, caplog.text)


def assert_private_data_absent(error, logs):
    rendered = "".join(traceback.format_exception(error)) if error is not None else ""
    for sensitive in (KEY, BASE, TEXT, BODY, "Authorization", "Bearer "):
        assert sensitive not in rendered + logs
