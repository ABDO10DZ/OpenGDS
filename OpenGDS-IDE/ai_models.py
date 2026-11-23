"""Model capability metadata shared by provider settings and the agent.

Unknown capabilities remain None rather than being guessed from a model name.
Provider model catalogs change frequently; callers may register verified
metadata obtained from a provider's current model list or explicit user config.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelCapabilities:
    provider: str
    model: str
    protocol: str
    streaming: Optional[bool] = None
    tool_calling: Optional[bool] = None
    vision: Optional[bool] = None
    context_window: Optional[int] = None


_CAPABILITIES: dict[tuple[str, str], dict[str, object]] = {}


def register_model_capabilities(
    provider: str,
    model: str,
    *,
    streaming: bool | None = None,
    tool_calling: bool | None = None,
    vision: bool | None = None,
    context_window: int | None = None,
) -> None:
    """Register explicitly verified capabilities for a provider/model pair."""
    name, model_id = str(provider).strip().lower(), str(model).strip()
    if not name or not model_id:
        raise ValueError("Provider and model IDs are required.")
    if context_window is not None and int(context_window) <= 0:
        raise ValueError("context_window must be a positive integer.")
    _CAPABILITIES[(name, model_id)] = {
        "streaming": streaming,
        "tool_calling": tool_calling,
        "vision": vision,
        "context_window": int(context_window) if context_window is not None else None,
    }


def describe_model(provider: str, model: str, protocol: str = "openai") -> ModelCapabilities:
    """Describe a selected model without inventing unknown feature support."""
    name, model_id = str(provider).strip(), str(model).strip()
    values = _CAPABILITIES.get((name.lower(), model_id), {})
    return ModelCapabilities(
        provider=name,
        model=model_id,
        protocol=str(protocol or "openai").strip().lower(),
        streaming=values.get("streaming"),
        tool_calling=values.get("tool_calling"),
        vision=values.get("vision"),
        context_window=values.get("context_window"),
    )
