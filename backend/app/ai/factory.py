"""Build the pinned LangChain model; never connect or silently change models."""

from app.ai.registry import get_spec
from app.ai.settings import load_llm_settings


def get_chat_model(role="tool", *, settings=None, http_client=None, http_async_client=None):
    settings = settings or load_llm_settings()
    if role not in {"tool", "chat"}:
        raise ValueError("Unknown campus model role")
    spec = get_spec(settings.model_id)
    if role == "tool" and not spec.capabilities.tools:
        raise ValueError("The approved model does not support tools")
    if not settings.configured:
        raise ValueError("Configure CAMPUS_LLM_API_KEY and CAMPUS_LLM_BASE_URL first")
    if settings.enable_thinking and not spec.capabilities.thinking:
        raise ValueError("The approved model does not support thinking")
    from app.ai.bailian import BailianChatOpenAI

    return BailianChatOpenAI(
        model=spec.id, base_url=settings.base_url, api_key=settings.api_key,
        timeout=settings.timeout_s, max_retries=0,
        max_tokens=min(settings.max_output_tokens, spec.capabilities.max_out),
        extra_body={spec.thinking_param: settings.enable_thinking}
        if spec.capabilities.thinking else {},
        stream_usage=True, use_responses_api=False,
        http_client=http_client, http_async_client=http_async_client,
    )
