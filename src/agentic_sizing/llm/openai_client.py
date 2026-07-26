from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract import StructuredGenerationRequest, StructuredGenerationResult

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - dependency guard
    OpenAI = None  # type: ignore[assignment]


def _supports_reasoning(model: str) -> bool:
    normalized = model.lower()
    return normalized.startswith("gpt-5") or normalized.startswith("o")


class OpenAIStructuredLLMClient:
    """OpenAI Responses API client implementing the shared structured-output contract."""

    def __init__(self, api_key: str | None = None) -> None:
        if OpenAI is None:
            raise ImportError(
                "openai package is required for structured LLM calls. Install dependencies from "
                "the `openai` extra: python -m pip install 'agentic-sizing[openai]'"
            )
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI structured LLM calls.")
        self.client = OpenAI(api_key=key)

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        if request.provider.lower() != "openai":
            raise ValueError(
                f"OpenAIStructuredLLMClient does not support provider: {request.provider}"
            )

        response_kwargs: dict[str, Any] = {
            "model": request.model,
            "input": [
                {
                    "role": message.role,
                    "content": [{"type": "input_text", "text": message.content}],
                }
                for message in request.messages
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "strict": request.strict,
                    "schema": request.schema,
                }
            },
        }

        # GPT-5-family models currently do not accept temperature in Responses API.
        if not request.model.lower().startswith("gpt-5"):
            response_kwargs["temperature"] = request.temperature

        if request.max_output_tokens is not None:
            response_kwargs["max_output_tokens"] = request.max_output_tokens
        # Reasoning controls are only accepted by reasoning-capable model families.
        if request.reasoning_effort is not None and _supports_reasoning(request.model):
            response_kwargs["reasoning"] = {"effort": request.reasoning_effort}

        response = self.client.responses.create(**response_kwargs)

        payload_text = self._extract_output_text(response)
        usage = self._extract_usage(response)
        try:
            parsed = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse structured response as JSON: {exc}") from exc

        request_id = getattr(response, "id", None)
        self._record_usage(
            provider="openai",
            model=request.model,
            schema_name=request.schema_name,
            request_id=request_id,
            usage=usage,
        )

        return StructuredGenerationResult(
            provider="openai",
            model=request.model,
            output_json=parsed,
            raw_text=payload_text,
            request_id=request_id,
            usage=usage,
        )

    @staticmethod
    def _extract_output_text(response: Any) -> str:
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text

        output_items = getattr(response, "output", None) or []
        for item in output_items:
            for content in getattr(item, "content", None) or []:
                content_type = getattr(content, "type", "")
                if content_type in {"output_text", "text"}:
                    candidate = getattr(content, "text", None)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate

        raise RuntimeError("OpenAI response did not contain output text.")

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}

        payload: dict[str, Any] = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
        ):
            value = getattr(usage, key, None)
            if isinstance(value, int):
                payload[key] = value

        for key in ("input_tokens_details", "output_tokens_details"):
            value = getattr(usage, key, None)
            if value is not None:
                payload[key] = OpenAIStructuredLLMClient._to_jsonable(value)

        return payload

    @staticmethod
    def _record_usage(
        *,
        provider: str,
        model: str,
        schema_name: str,
        request_id: str | None,
        usage: dict[str, Any],
    ) -> None:
        usage_path = os.getenv("AGENTIC_LLM_USAGE_PATH", "").strip()
        if not usage_path:
            return

        path = Path(usage_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "schema_name": schema_name,
            "request_id": request_id,
            "usage": usage,
        }
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=True) + "\n")

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(k): OpenAIStructuredLLMClient._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [OpenAIStructuredLLMClient._to_jsonable(item) for item in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return OpenAIStructuredLLMClient._to_jsonable(model_dump())
        return str(value)
