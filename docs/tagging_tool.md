# Tagging Tool

## Purpose

Manual 2-stage structural tagging tool (outside LangGraph runtime):

- Stage 1: functional role partitioning
- Stage 2: substructure tagging

## Code and Prompt

- Pipeline: `agentic_sizing/tagging/pipeline.py`
- CLI: `agentic_sizing/tagging/__main__.py`
- Prompts:
  - `agentic_sizing/resources/prompts/tagging/step1_functional_role_partitioning.md`
  - `agentic_sizing/resources/prompts/tagging/step2_substructure_tagging.md`

## Run

```bash
cd .
python -m agentic_sizing.tagging \
  --input examples/tagging/5t_ota \
  --output output/tagging/5t_ota.tagging.json \
  --model gpt-5.2 \
  --max-retries 2 \
  --temperature 0.5 \
  --reasoning-effort high
```

## Contract

- Schema:
  `agentic_sizing/tagging/tagging_output.schema.json`
- Example:
  `agentic_sizing/tagging/tagging_output.example.json`

Output is a single JSON object.
