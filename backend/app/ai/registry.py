"""Approved chat model capabilities, independent of credentials and pricing."""

from dataclasses import dataclass

from app.ai.settings import MODEL_ID


@dataclass(frozen=True)
class Capabilities:
    tools: bool
    thinking: bool
    json_mode: bool
    max_out: int
    vision: bool = False
    json_schema: bool = False


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    capabilities: Capabilities
    thinking_param: str = "enable_thinking"


MODEL_REGISTRY = {MODEL_ID: ModelSpec(
    id=MODEL_ID, provider="dashscope",
    capabilities=Capabilities(tools=True, thinking=True, json_mode=True, max_out=2048),
)}


def get_spec(model_id: str) -> ModelSpec:
    try:
        return MODEL_REGISTRY[model_id]
    except KeyError:
        raise ValueError("Unknown campus model ID") from None
