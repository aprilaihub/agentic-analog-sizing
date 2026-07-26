from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.llm.contract import (
    LLMMessage,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from agentic_sizing.llm.factory import create_structured_client
from agentic_sizing.llm.openai_client import OpenAIStructuredLLMClient


class TestLLMContract(unittest.TestCase):
    def test_request_response_models(self) -> None:
        request = StructuredGenerationRequest(
            provider="openai",
            model="gpt-5.2",
            messages=[LLMMessage(role="system", content="Return JSON.")],
            schema_name="demo_schema",
            schema={"type": "object"},
            strict=True,
            temperature=0.5,
            max_output_tokens=256,
            reasoning_effort="high",
        )
        result = StructuredGenerationResult(
            provider="openai",
            model="gpt-5.2",
            output_json={"ok": True},
            raw_text='{"ok": true}',
            request_id="resp_123",
        )
        self.assertEqual(request.provider, "openai")
        self.assertEqual(request.messages[0].role, "system")
        self.assertEqual(request.reasoning_effort, "high")
        self.assertEqual(result.output_json["ok"], True)

    def test_factory_rejects_unknown_provider(self) -> None:
        with self.assertRaises(ValueError):
            create_structured_client(provider="unknown_provider")

    def test_factory_selects_openai_provider(self) -> None:
        try:
            client = create_structured_client(provider="openai", api_key="test-key")
        except ImportError as exc:
            self.skipTest(f"openai unavailable: {exc}")
        self.assertIsInstance(client, OpenAIStructuredLLMClient)

    def test_openai_key_missing_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises((ValueError, ImportError)):
                create_structured_client(provider="openai")

    def test_openai_client_passes_reasoning_effort(self) -> None:
        class _FakeResponses:
            def __init__(self) -> None:
                self.kwargs = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(id="resp_1", output_text='{"ok": true}', output=[])

        class _FakeOpenAI:
            def __init__(self, api_key: str | None = None) -> None:
                self.api_key = api_key
                self.responses = _FakeResponses()

        with patch("agentic_sizing.llm.openai_client.OpenAI", _FakeOpenAI):
            client = OpenAIStructuredLLMClient(api_key="test-key")
            req = StructuredGenerationRequest(
                provider="openai",
                model="gpt-5.2",
                messages=[LLMMessage(role="user", content="{}")],
                schema_name="x",
                schema={"type": "object"},
                strict=True,
                reasoning_effort="high",
            )
            client.generate_structured(req)
            create_kwargs = client.client.responses.kwargs
            self.assertEqual(create_kwargs["reasoning"], {"effort": "high"})
            self.assertNotIn("temperature", create_kwargs)


if __name__ == "__main__":
    unittest.main()
