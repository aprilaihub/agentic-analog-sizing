from __future__ import annotations

from typing import Any

from .contract import StructuredLLMClient
from .openai_client import OpenAIStructuredLLMClient


def create_structured_client(
    provider: str = "openai",
    api_key: str | None = None,
    **kwargs: Any,
) -> StructuredLLMClient:
    normalized = provider.lower().strip()
    if normalized == "openai":
        return OpenAIStructuredLLMClient(api_key=api_key, **kwargs)
    raise ValueError(f"Unsupported LLM provider: {provider}")
