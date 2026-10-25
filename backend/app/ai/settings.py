"""Explicit, independent chat configuration; no .env loading or import-time I/O."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit


MODEL_ID = "deepseek-v4.1-flash-1017"


def validate_base_url(value: str) -> None:
    if not value:
        return
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        valid_host = host == "dashscope.aliyuncs.com" or bool(re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9-]*\.cn-beijing\.maas\.aliyuncs\.com", host))
        valid = (url.scheme == "https" and valid_host and url.port in {None, 443}
                 and not url.username and not url.password and not url.query
                 and not url.fragment and url.path == "/compatible-mode/v1")
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("CAMPUS_LLM_BASE_URL must be a Bailian Beijing HTTPS endpoint")


@dataclass(frozen=True)
class LLMSettings:
    model_id: str = MODEL_ID
    base_url: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    timeout_s: int = 30
    enable_thinking: bool = False
    max_output_tokens: int = 2048

    def __post_init__(self):
        if self.model_id != MODEL_ID:
            raise ValueError("CAMPUS_LLM_MODEL_ID is not an approved model")
        validate_base_url(self.base_url)
        if type(self.timeout_s) is not int or not 1 <= self.timeout_s <= 45:
            raise ValueError("CAMPUS_LLM_TIMEOUT_S must be between 1 and 45")
        if type(self.enable_thinking) is not bool:
            raise ValueError("CAMPUS_LLM_ENABLE_THINKING must be true or false")
        if type(self.max_output_tokens) is not int or not 64 <= self.max_output_tokens <= 2048:
            raise ValueError("CAMPUS_LLM_MAX_OUTPUT_TOKENS must be between 64 and 2048")
        if not isinstance(self.api_key, str) or any(char.isspace() for char in self.api_key):
            raise ValueError("CAMPUS_LLM_API_KEY has an invalid format")

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)


def _integer(source, name, default):
    try:
        return int(source.get(name, str(default)))
    except (TypeError, ValueError):
        raise ValueError(name + " must be an integer") from None


def load_llm_settings(environ: Mapping[str, str] | None = None) -> LLMSettings:
    source = os.environ if environ is None else environ
    thinking = source.get("CAMPUS_LLM_ENABLE_THINKING", "false").strip().lower()
    if thinking not in {"true", "false"}:
        raise ValueError("CAMPUS_LLM_ENABLE_THINKING must be true or false")
    return LLMSettings(
        model_id=source.get("CAMPUS_LLM_MODEL_ID", MODEL_ID).strip(),
        base_url=source.get("CAMPUS_LLM_BASE_URL", "").strip().rstrip("/"),
        api_key=source.get("CAMPUS_LLM_API_KEY", "").strip(),
        timeout_s=_integer(source, "CAMPUS_LLM_TIMEOUT_S", 30),
        enable_thinking=thinking == "true",
        max_output_tokens=_integer(source, "CAMPUS_LLM_MAX_OUTPUT_TOKENS", 2048),
    )
