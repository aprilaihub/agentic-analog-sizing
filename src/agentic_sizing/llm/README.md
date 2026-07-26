# Shared LLM Contract

This package defines a provider-agnostic structured-generation contract and provider implementations.

## Contract

- `StructuredLLMClient.generate_structured(request: StructuredGenerationRequest) -> StructuredGenerationResult`

Request fields:
- `provider`
- `model`
- `messages`
- `schema_name`
- `schema`
- `strict`
- `temperature`
- `max_output_tokens`
- `reasoning_effort` (`low|medium|high`, optional)

Response fields:
- `provider`
- `model`
- `output_json`
- `raw_text`
- `request_id`

## Factory

- `create_structured_client(provider="openai", api_key=None, **kwargs)`

Current providers:
- `openai` via Responses API structured outputs.

Provider note:
- GPT-5-family models do not currently accept `temperature` in Responses API; the OpenAI client omits it automatically for those models.
