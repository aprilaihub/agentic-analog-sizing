# Agentic Sizing Runbook

This document explains how to run the sizing workflow end-to-end from prepared `input` files.

## What You Will Run

The practical flow is:
1. Generate structural tagging from netlist.
2. Generate 3 KB view files from settings + improving designs + tagging.
3. Run the LangGraph sizing loop (initialize + iterative sizing + simulation commit).

Main implementation path:
- `src/agentic_sizing`

Reference-only data:
- `reference/kb`
- `reference/tagging`

## Inputs and Outputs

The repository includes these public input examples:
- `input/tagging/5t_ota`
- `input/kb/5t_ota_settings.json`
- `input/kb/5t_ota_improving_designs.json`

Runtime outputs are written to:
- `output/tagging/`
- `output/kb/`
- `output/simulation_record.json`

Runtime KB baseline (read-only) is stored at:
- `output/kb/pillars/`

## Prerequisites

From repo root:
```bash
cd agentic-analog-sizing
```

Install dependencies:
```bash
python -m pip install -r requirements.txt
```

Set OpenAI key (required for tagging / KB extraction / LLM planner-worker):
```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY
export OPENAI_API_KEY
```

Optional (if you store secrets in `.env.local`):
```bash
set -a
source .env.local
set +a
```

## Step 1: Run Tagging

```bash
python -m agentic_sizing.tagging \
  --input input/tagging/5t_ota \
  --output output/tagging/5t_ota.tagging.json \
  --model gpt-5.2 \
  --max-retries 2 \
  --temperature 0.5 \
  --reasoning-effort high
```

Expected output:
- `output/tagging/5t_ota.tagging.json`

## Step 2: Run KB Extraction (Offline)

```bash
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

Expected outputs:
- `output/kb/5t_ota_kb_perf_tradeoff.json`
- `output/kb/5t_ota_kb_substruct_param_perf.json`
- `output/kb/5t_ota_kb_role_perf.json`

## Step 3: Run Sizing Loop (Mock Simulation)

Use this first to validate full control flow without Cadence.

```bash
agentic-sizing run \
  --netlist input/tagging/5t_ota \
  --kb-root output/kb \
  --max-iter 3 \
  --max-stagnation 3 \
  --max-planner-worker-iter 10 \
  --mode mock \
  --simulation-record-path output/simulation_record.json \
  --show-history
```

What this does:
- `simulate_init`: resets runtime KB from the fixed `global` baseline, then initializes the run.
- iterative loop: planner/worker updates until commit condition.
- `simulate_commit`: appends one record to `output/simulation_record.json`.

Expected updated artifacts:
- `output/simulation_record.json` (append)
- Three runtime KB views in `output/kb/` copied from the baseline at startup

## Step 4: Run Sizing Loop (Real Cadence)

After Cadence environment is configured:

```bash
agentic-sizing run \
  --netlist input/tagging/5t_ota \
  --kb-root output/kb \
  --max-iter 5 \
  --max-stagnation 5 \
  --max-planner-worker-iter 10 \
  --mode real \
  --simulation-record-path output/simulation_record.json \
  --show-history
```

Cadence setup details:
- `docs/simulator_tool.md`
- `src/agentic_sizing/simulator/README.md`

## Quick Validation Commands

Check last simulation record:
```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('output/simulation_record.json')
if not p.exists():
    print('missing simulation record file')
else:
    data = json.loads(p.read_text())
    print('records:', len(data))
    print('last_iter:', data[-1]['iter'] if data else None)
PY
```

## Important Path Rule

Case name is inferred from `--netlist` file name/stem.
- For case `5t_ota`, pass a netlist path whose basename is `5t_ota`.
- Otherwise the workflow will look for different `<case>_*.json` files.

## Runtime KB Seed Rule

- `output/kb/pillars/` is treated as read-only baseline KB.
- Each run startup copies the three `global_kb_*.json` baseline files.
- Copied targets are `output/kb/<case>_kb_*.json` and are always overwritten.

## Other Tool Docs

- KB tool details: `docs/kb_tool.md`
- Tagging tool details: `docs/tagging_tool.md`
- Initialize tool details: `docs/initialize_tool.md`
- Iterative sizing details: `docs/iterative_sizing_tool.md`
- Workflow details: `docs/llm_agentic_sizing_workflow.md`
