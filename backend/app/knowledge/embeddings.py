"""Bailian's fixed embedding configuration, with no synthetic fallback."""

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import math
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


logger = logging.getLogger(__name__)

FAILURE_MESSAGES = {
    "authentication": "百炼嵌入服务鉴权失败，请检查本地密钥、地域和模型权限。",
    "rate_limited": "百炼嵌入服务请求过于频繁，请稍后重试。",
    "timeout": "百炼嵌入服务响应超时，请稍后重试。",
    "network": "暂时无法连接百炼嵌入服务，请稍后重试。",
    "invalid_response": "百炼嵌入服务返回结果无效，请稍后重试。",
    "invalid_request": "知识库嵌入请求无效，请检查文本或服务配置。",
    "upstream": "百炼嵌入服务暂不可用，请稍后重试。",
    "configuration": "知识库嵌入服务配置无效，请检查本地配置。",
    "unavailable": "知识库嵌入服务暂不可用，请稍后重试。",
}


class EmbeddingUnavailable(RuntimeError):
    """The configured embedding service could not produce usable vectors."""

    def __init__(self, message=FAILURE_MESSAGES["unavailable"], *, reason="unavailable"):
        self.reason = reason if isinstance(reason, str) and reason in FAILURE_MESSAGES else "unavailable"
        super().__init__(message)


def _failure(reason):
    return EmbeddingUnavailable(FAILURE_MESSAGES[reason], reason=reason)


def _retry_delay(response, attempt):
    fallback = 0.25 * (2 ** (attempt - 1))
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return fallback
    try:
        delay = float(value)
        if not math.isfinite(delay) or delay < 0:
            return fallback
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            delay = max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return fallback
    return min(5.0, delay)


def _status_reason(status):
    if status in {401, 403}:
        return "authentication"
    if status == 429:
        return "rate_limited"
    if status in {408, 504}:
        return "timeout"
    if 500 <= status <= 599:
        return "upstream"
    if 400 <= status <= 499:
        return "invalid_request"
    return "invalid_response"


class BailianEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "text-embedding-v4",
        dimensions: int = 1024,
        timeout_s: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
        total_timeout_s: float = 45,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip() or "\r" in api_key or "\n" in api_key:
            raise EmbeddingUnavailable("知识库嵌入服务尚未配置。", reason="configuration")
        try:
            parsed = urlsplit(base_url)
            valid_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
            )
            parsed.port
        except (TypeError, ValueError, AttributeError):
            valid_url = False
        if not valid_url:
            raise EmbeddingUnavailable("知识库嵌入服务地址未正确配置。", reason="configuration")
        if model != "text-embedding-v4" or type(dimensions) is not int or dimensions != 1024:
            raise EmbeddingUnavailable("知识库嵌入服务必须使用 text-embedding-v4 和 1024 维。", reason="configuration")
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s)
            or timeout_s <= 0
        ):
            raise EmbeddingUnavailable("知识库嵌入服务超时配置无效。", reason="configuration")
        if (
            isinstance(total_timeout_s, bool)
            or not isinstance(total_timeout_s, (int, float))
            or not math.isfinite(total_timeout_s)
            or total_timeout_s <= 0
        ):
            raise EmbeddingUnavailable("知识库嵌入服务总超时配置无效。", reason="configuration")
        self._api_key = api_key.strip()
        self._endpoint = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._dimensions = dimensions
        self._timeout = float(timeout_s)
        self._transport = transport
        self._total_timeout = total_timeout_s

    def _read_vectors(self, payload: object, count: int) -> list[list[float]]:
        if not isinstance(payload, dict):
            raise ValueError("Invalid embedding response")
        if "model" in payload and payload["model"] != self._model:
            raise ValueError("Unexpected embedding model")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != count:
            raise ValueError("Incomplete embedding response")
        ordered: list[list[float] | None] = [None] * count
        for entry in data:
            if not isinstance(entry, dict):
                raise ValueError("Invalid embedding record")
            position = entry.get("index")
            if type(position) is not int or not 0 <= position < count or ordered[position] is not None:
                raise ValueError("Invalid embedding positions")
            raw = entry.get("embedding")
            if not isinstance(raw, list) or len(raw) != self._dimensions:
                raise ValueError("Invalid embedding dimensions")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in raw
            ):
                raise ValueError("Invalid embedding numbers")
            vector = [float(value) for value in raw]
            if not any(value != 0 for value in vector):
                raise ValueError("Empty embedding vector")
            ordered[position] = vector
        if any(value is None for value in ordered):
            raise ValueError("Missing embedding positions")
        return [value for value in ordered if value is not None]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or any(not isinstance(value, str) or not value.strip() for value in texts):
            raise EmbeddingUnavailable("知识库文本无法生成有效向量。", reason="invalid_request")
        if not texts:
            return []
        result: list[list[float]] = []
        request_id = uuid4().hex
        started = time.monotonic()
        status, attempt, batch_size = None, 0, 0
        try:
            async with asyncio.timeout(self._total_timeout):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as client:
                    for offset in range(0, len(texts), 10):
                        batch = texts[offset:offset + 10]
                        batch_size = len(batch)
                        for attempt in range(1, 4):
                            status = None
                            try:
                                response = await client.post(
                                    self._endpoint,
                                    headers={"Authorization": "Bearer " + self._api_key},
                                    json={
                                        "model": self._model,
                                        "input": batch,
                                        "dimensions": self._dimensions,
                                        "encoding_format": "float",
                                    },
                                )
                            except httpx.TimeoutException:
                                raise _failure("timeout") from None
                            except httpx.RequestError:
                                raise _failure("network") from None
                            status = response.status_code
                            retryable = status == 429 or 500 <= status <= 599
                            if retryable and attempt < 3:
                                delay = _retry_delay(response, attempt)
                                logger.warning(
                                    "embedding_request outcome=retry request_id=%s status=%s attempt=%d batch_size=%d elapsed_ms=%d reason=%s delay_s=%s",
                                    request_id, status, attempt, batch_size,
                                    int((time.monotonic() - started) * 1000), _status_reason(status), delay,
                                )
                                await asyncio.sleep(delay)
                                continue
                            if not response.is_success:
                                raise _failure(_status_reason(status))
                            try:
                                result.extend(self._read_vectors(response.json(), batch_size))
                            except (ValueError, TypeError):
                                raise _failure("invalid_response") from None
                            logger.info(
                                "embedding_request outcome=success request_id=%s status=%s attempt=%d batch_size=%d elapsed_ms=%d reason=none",
                                request_id, status, attempt, batch_size,
                                int((time.monotonic() - started) * 1000),
                            )
                            break
            return result
        except (EmbeddingUnavailable, TimeoutError) as error:
            reason = "timeout" if isinstance(error, TimeoutError) else error.reason
        except Exception:
            reason = "unavailable"
        # Only controlled metadata is logged. No exception, upstream body, input,
        # URL or credential reaches either logs or the outward exception.
        logger.warning(
            "embedding_request outcome=failed request_id=%s status=%s attempt=%d batch_size=%d elapsed_ms=%d reason=%s",
            request_id, status, attempt, batch_size,
            int((time.monotonic() - started) * 1000), reason,
        )
        raise _failure(reason) from None
