from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class StructuredGenerationRequest:
    provider: str
    model: str
    messages: List[LLMMessage]
    schema_name: str
    schema: Dict[str, Any]
    strict: bool = True
    temperature: float = 0.5
    max_output_tokens: Optional[int] = None
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = None


@dataclass(frozen=True)
class StructuredGenerationResult:
    provider: str
    model: str
    output_json: Any
    raw_text: str
    request_id: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class StructuredLLMClient(Protocol):
    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        """Generate schema-constrained JSON using a provider-specific model API."""
