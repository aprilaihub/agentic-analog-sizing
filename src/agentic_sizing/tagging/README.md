# Two-Stage Tagging Tool

This module provides a manual (CLI-driven) two-stage structural tagging flow using OpenAI structured outputs.

## Location
- Code: `src/agentic_sizing/tagging/`
- Prompts: `src/agentic_sizing/resources/prompts/tagging/`

## Run
```bash
cd agentic-analog-sizing
agentic-sizing tag \
  --input input/tagging/ldo \
  --output output/tagging/ldo.tagging.json \
  --model gpt-5.2 \
  --max-retries 2 \
  --reasoning-effort high
```

Environment variable required:
- `OPENAI_API_KEY`

Load credentials from your shell or secret manager before running:
```bash
export OPENAI_API_KEY
```

If the CLI ends with `Connection error`, the most common causes are:
- the active Python environment differs from the one where `openai` was installed
- outbound network access to OpenAI is blocked or intermittent
- proxy/TLS settings in the shell are interfering with the request

## Public API
- `run_two_stage_tagging(input_path, output_path=None, model="gpt-5.2", max_retries=2, temperature=0.5, reasoning_effort="high", llm_client=None) -> dict`
- Shared LLM contract:
  `src/agentic_sizing/llm/contract.py`
- Shared OpenAI implementation:
  `src/agentic_sizing/llm/openai_client.py`
- Shared factory:
  `src/agentic_sizing/llm/factory.py`

## Data Contract
- Contract schema (source of truth):
  `src/agentic_sizing/tagging/tagging_output.schema.json`
- Runtime schema constant:
  `src/agentic_sizing/tagging/schemas.py` (`FINAL_OUTPUT_SCHEMA`)
- Example payload:
  `src/agentic_sizing/tagging/tagging_output.example.json`

## Output
Single JSON with:
- `schema_version`
- `tool`
- `input`
- `stage1.functional_roles`
- `stage2.roles[].substructures`
- `validation`
