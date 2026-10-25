"""Pinned Chat Completions wire adaptation for the approved Bailian model."""

from langchain_openai import ChatOpenAI


class BailianChatOpenAI(ChatOpenAI):
    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        raw = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, raw.get("choices", [])):
            # Only retain an observation flag; never retain the reasoning text.
            generation.message.response_metadata["reasoning_observed"] = bool(
                (choice.get("message") or {}).get("reasoning_content"))
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # LangChain 1.0.3 rewrites max_tokens to OpenAI's newer parameter name.
        # Use the documented Bailian Chat Completions field explicitly.
        maximum = payload.pop("max_completion_tokens", self.max_tokens)
        if type(maximum) is not int or not 0 < maximum <= self.max_tokens:
            raise ValueError("Model output limit cannot exceed the configured policy")
        payload["max_tokens"] = maximum
        if payload.get("model") != self.model_name:
            raise ValueError("The configured model cannot be overridden")
        extra = payload.get("extra_body") or {}
        if set(extra) & {"model", "max_tokens", "max_completion_tokens", "api_key", "base_url"}:
            raise ValueError("Protected model parameters cannot be overridden")
        return payload
