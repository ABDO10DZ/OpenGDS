"""Provider transport adapters for OpenGDS-IDE's AI agent.

Adapters own endpoint and authentication differences. Conversation/tool-loop
policy remains in AgentEngine so approval and workspace-safety behavior stays
provider-neutral.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ProviderAdapter:
    protocol: str

    def chat_endpoint(self, base_url: str) -> str:
        raise NotImplementedError

    def headers(self, api_key: str, provider_name: str = "") -> dict[str, str]:
        raise NotImplementedError


@dataclass(frozen=True)
class OpenAICompatibleAdapter(ProviderAdapter):
    protocol: str = "openai"

    def chat_endpoint(self, base_url: str) -> str:
        base = str(base_url or "").rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    def headers(self, api_key: str, provider_name: str = "") -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key or ''}",
            "Content-Type": "application/json",
        }
        if provider_name in {"OpenRouter", "OpenRouter Free"}:
            headers.update({
                "HTTP-Referer": "https://github.com/ABDO10DZ/OpenGDS",
                "X-Title": "OpenGDS-IDE",
            })
        return headers


@dataclass(frozen=True)
class AnthropicAdapter(ProviderAdapter):
    protocol: str = "anthropic"

    def chat_endpoint(self, base_url: str) -> str:
        base = str(base_url or "").rstrip("/")
        return base if base.endswith("/messages") else base + "/messages"

    def headers(self, api_key: str, provider_name: str = "") -> dict[str, str]:
        return {
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }


_ADAPTERS: Mapping[str, ProviderAdapter] = {
    "openai": OpenAICompatibleAdapter(),
    "anthropic": AnthropicAdapter(),
}


def get_provider_adapter(protocol: str) -> ProviderAdapter:
    """Return a stateless adapter for a supported wire protocol."""
    name = str(protocol or "openai").strip().lower()
    try:
        return _ADAPTERS[name]
    except KeyError:
        raise ValueError(f"Unsupported AI provider protocol: {name}") from None
