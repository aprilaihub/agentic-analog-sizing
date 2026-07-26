# Initialize Tool (Planner-Worker)

## Purpose

Initialize stage for LangGraph:

1. Planner ranks functional roles and emits sequential worker instructions.
2. Worker generates initial values for role-owned design variables.
3. One simulation is executed and record is appended to `output/simulation_record.json`.

This stage is wired into LangGraph node `simulate_init`.

## Code Paths

- Pipeline: `src/agentic_sizing/initialization/pipeline.py`
- Planner: `src/agentic_sizing/initialization/initialize_planner.py`
- Worker: `src/agentic_sizing/initialization/initialize_worker.py`
- Record store: `src/agentic_sizing/initialization/record_store.py`
- Schemas: `src/agentic_sizing/initialization/schemas.py`
- Prompts:
  - `src/agentic_sizing/resources/prompts/initialization/initialize_planner.md`
  - `src/agentic_sizing/resources/prompts/initialization/initialize_worker.md`

## Case Path Inference

Given `netlist_path`, case is inferred from filename stem.

For `5t_ota`:
- settings: `input/kb/5t_ota_settings.json`
- design specs output: `output/kb/5t_ota_design_specs.json`
- tagging: `output/tagging/5t_ota.tagging.json`
- kb perf tradeoff: `output/kb/5t_ota_kb_perf_tradeoff.json`
- kb role perf: `output/kb/5t_ota_kb_role_perf.json`

Before loading runtime KB files, initialization copies the three read-only
`output/kb/pillars/global_kb_*.json` baseline files.
If seed files are missing/incomplete/invalid, initialize stage fails immediately.
Startup always overwrites the runtime KB views.

## Simulation Record Contract

Path:
- `output/simulation_record.json`

Top-level:
- JSON array

Each record:
- `iter` (int, >=1)
- `parameters` (number array in `settings.des_vars` order)
- `performance` (number array in `settings.responses.assembler` order)

## Runtime mode

- `--mode real` (default): LLM initialization with Cadence simulation.
- `--mode mock`: mock initialization and simulation for tests/debugging.

## Runner Example

```bash
cd agentic-analog-sizing
agentic-sizing run \
  --netlist input/tagging/5t_ota \
  --kb-root output/kb \
  --mode mock \
  --simulation-record-path output/simulation_record.json \
  --max-iter 2 \
  --max-stagnation 2 \
  --show-history
```

Note:
- `--mode real` requires an OpenAI API key and Cadence runtime.
