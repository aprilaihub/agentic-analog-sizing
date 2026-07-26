# KB Fact Extraction Tool

This module provides a CLI-driven 4-step extraction flow using strict structured LLM outputs:

1. Performance coupling facts.
2. Critical substructure/parameter facts.
3. Role/performance facts.
4. Transferable design heuristics.

## Location
- Code: `src/agentic_sizing/kb/`
- Prompt templates:
  - `src/agentic_sizing/resources/prompts/kb/step1_perf_tradeoff.md`
  - `src/agentic_sizing/resources/prompts/kb/step2_substruct_param_perf.md`
  - `src/agentic_sizing/resources/prompts/kb/step3_role_perf.md`
- Shared LLM contract: `src/agentic_sizing/llm/contract.py`

## Run

```bash
cd agentic-analog-sizing
agentic-sizing extract-kb \
  --settings input/kb/folded_cascode_settings.json \
  --improving-designs input/kb/folded_cascode_improving_designs.json \
  --tagging ${CADENCE_PROJECT_DIR}/src/agentic_sizing/tagging/tagging_output.example.json \
  --output-dir output/kb/pillars \
  --output-prefix folded_cascode \
  --merge-existing "output/kb/*.json" \
  --provider openai \
  --model gpt-5.2 \
  --max-retries 2 \
  --reasoning-effort high
```

### Incrementally extract and merge a new case

The following example generates an improving-design trace from a raw two-stage
folded-cascode simulation record, extracts its three KB views, and merges them
into the existing global pillar views:

```bash
cd agentic-analog-sizing

agentic-sizing extract-kb \
  --settings input/kb/folded_cascode_2stage_settings.json \
  --simulation-record output/20260608_112013_simulation_record.json \
  --tagging output/tagging/folded_cascode_2stage.tagging.json \
  --output-dir output/kb/pillars \
  --output-prefix folded_cascode_2stage \
  --provider openai \
  --model gpt-5.2 \
  --max-retries 2 \
  --reasoning-effort high \
  --merge-existing \
    'output/kb/pillars/global_kb_perf_tradeoff.json' \
    'output/kb/pillars/global_kb_substruct_param_perf.json' \
    'output/kb/pillars/global_kb_role_perf.json'
```

This command:

1. Writes `input/kb/folded_cascode_2stage_improving_designs.json`.
2. Writes the three `folded_cascode_2stage_kb_*.json` pillar files.
3. Merges those generated facts with the existing `global_kb_*.json` facts.
4. Rewrites the three `global_kb_*.json` files in `output/kb/pillars`.

The newly generated case files are included automatically. Do not also pass
them through `--merge-existing`, or their evidence will be counted twice.

### Transferable heuristic output

Every extraction also writes:

- `output/critical_heuristics/<case>_critical_heuristics.json`
- `output/critical_heuristics/global_critical_heuristics.json`

The case file retains the existing array format with `case_name`, `condition`,
`heuristic`, `priority`, and `scope`. The global file is rebuilt from all case
heuristic files. Planner and worker retrieval combines case-specific heuristics
with global heuristics matched by target metric and scope, allowing design
strategy to transfer when parameter names or circuit structure change.

Use `--disable-heuristic-extraction` to run only the original three fact stages,
or `--heuristics-output-dir` to select a different heuristic directory.

Environment variable required by OpenAI provider:
- `OPENAI_API_KEY`

## Public API
- `run_kb_fact_extraction(settings_path, improving_designs_path, tagging_path, output_dir=None, output_prefix=None, provider="openai", model="gpt-5.2", max_retries=2, temperature=0.5, reasoning_effort="high", api_key=None, llm_client=None) -> dict`

## Output Contract
The tool writes exactly 3 files:
- `<prefix>_kb_perf_tradeoff.json`
- `<prefix>_kb_substruct_param_perf.json`
- `<prefix>_kb_role_perf.json`
- `global_kb.json`

Each file is an object wrapper:
- `{"facts": [...]}`

Schema contracts:
- `kb_perf_tradeoff.schema.json`
- `kb_substruct_param_perf.schema.json`
- `kb_role_perf.schema.json`

Examples:
- `kb_perf_tradeoff.example.json`
- `kb_substruct_param_perf.example.json`
- `kb_role_perf.example.json`

Direction normalization (runtime validator):
- `positive`: `{increase_improves, direct}`
- `negative`: `{increase_degrades, inverse}`
