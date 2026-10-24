"""Bailian's fixed embedding configuration, with no synthetic fallback."""

import asyncio
import math
from urllib.parse import urlsplit

import httpx


class EmbeddingUnavailable(RuntimeError):
    """The configured embedding service could not produce usable vectors."""


class BailianEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "text-embedding-v4",
        dimensions: int = 1024,
        timeout_s: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip() or "\r" in api_key or "\n" in api_key:
            raise EmbeddingUnavailable("知识库嵌入服务尚未配置。")
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
            raise EmbeddingUnavailable("知识库嵌入服务地址未正确配置。")
        if model != "text-embedding-v4" or type(dimensions) is not int or dimensions != 1024:
            raise EmbeddingUnavailable("知识库嵌入服务必须使用 text-embedding-v4 和 1024 维。")
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s)
            or timeout_s <= 0
        ):
            raise EmbeddingUnavailable("知识库嵌入服务超时配置无效。")
        self._api_key = api_key.strip()
        self._endpoint = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._dimensions = dimensions
        self._timeout = float(timeout_s)
        self._transport = transport

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
            raise EmbeddingUnavailable("知识库文本无法生成有效向量。")
        if not texts:
            return []
        result: list[list[float]] = []
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
            ) as client:
                for offset in range(0, len(texts), 10):
                    batch = texts[offset:offset + 10]
                    for attempt in range(3):
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
                        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
                        if retryable and attempt < 2:
                            await asyncio.sleep(0.25 * (2 ** attempt))
                            continue
                        if not response.is_success:
                            raise ValueError("Embedding request failed")
                        result.extend(self._read_vectors(response.json(), len(batch)))
                        break
            return result
        except Exception:
            # Neither upstream bodies, request URLs nor credentials enter errors.
            raise EmbeddingUnavailable("知识库嵌入服务暂不可用，请稍后重试。") from None
