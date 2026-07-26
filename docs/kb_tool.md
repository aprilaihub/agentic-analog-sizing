# KB Tool

## Scope
`agentic_sizing/kb` provides an offline extraction CLI that generates three KB
view files from `settings + improving_designs + tagging`.

KB storage has two layers:
- Baseline layer (read-only): `output/kb/pillars/<seed>_kb_*.json`
- Runtime layer (mutable): `output/kb/<case>_kb_*.json`

At sizing startup, the runtime layer is recreated from the fixed `global` baseline.

## Code and Prompts
- Offline pipeline: `src/agentic_sizing/kb/pipeline.py`
- Merge engine: `src/agentic_sizing/kb/merge.py`
- Offline prompts:
  - `src/agentic_sizing/resources/prompts/kb/step1_perf_tradeoff.md`
  - `src/agentic_sizing/resources/prompts/kb/step2_substruct_param_perf.md`
  - `src/agentic_sizing/resources/prompts/kb/step3_role_perf.md`

## Offline Run

```bash
cd agentic-analog-sizing
python -m agentic_sizing.kb \
  --settings input/kb/5t_ota_settings.json \
  --improving-designs input/kb/5t_ota_improving_designs.json \
  --tagging output/tagging/5t_ota.tagging.json \
  --output-dir output/kb \
  --output-prefix 5t_ota \
  --provider openai \
  --model gpt-5.2 \
  --max-retries 2 \
  --temperature 0.5 \
  --reasoning-effort high
```

If you only have a raw simulation record, the same command can generate the improving trace first:

```bash
python -m agentic_sizing.kb \
  --settings input/kb/bgr_settings.json \
  --simulation-record output/20260629_074734_simulation_record.json \
  --tagging output/tagging/bgr.tagging.json \
  --output-dir output/kb \
  --output-prefix bgr \
  --model gpt-5.2
```

This writes `input/kb/bgr_improving_designs.json` by default. It validates vector dimensions,
recomputes weighted constraint violations from settings, retains constraint-first improvements,
and limits the trace to 20 chronologically distributed points. Use `--max-improving-designs`
or `--improving-designs-output` to override those defaults.

## Contracts
Offline view files use:
- `{"facts": [...]}`

Schemas:
- `src/agentic_sizing/kb/kb_perf_tradeoff.schema.json`
- `src/agentic_sizing/kb/kb_substruct_param_perf.schema.json`
- `src/agentic_sizing/kb/kb_role_perf.schema.json`

Direction normalization:

- All extracted directional labels normalize to `unspecified`.
- KB consumers use parameter criticality and metric coupling without increase/decrease advice.
