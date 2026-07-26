# LLM Agentic Sizing Workflow

## Problem Statement
This project introduces an LLM-oriented agentic sizing framework for analog IC sizing. The current delivery is a state-machine scaffold only (no production sizing logic yet), designed to lock architecture and data contracts before implementation.

## Objective
Build a modular system that can:
- Build initialization candidates with planner-worker role sequencing.
- Run iterative sizing with one-metric one-role planner-worker dispatch.
- Keep role-scoped parameter updates and full-performance prediction loops.
- Update knowledge bases from committed simulation outcomes.

## Tagging Boundary
- Two-stage structural tagging is an external, manual workflow under `agentic_sizing/tagging`.
- LangGraph no longer runs decomposition/tagging nodes.
- LangGraph consumes pre-defined functional role ownership and focuses only on optimization loop execution.

## Standalone Tagging Tool Status
- A standalone two-stage tagging tool is implemented under `agentic_sizing/tagging`.
- Prompt templates are stored under `agentic_sizing/resources/prompts/tagging`.
- The tool uses OpenAI structured output and writes a single structural JSON artifact.
- Operation mode is manual (CLI-driven) and outside LangGraph runtime.

## Environment Setup

Install the package and development tools with pip:

```bash
python -m pip install -e '.[openai,cadence,dev]'
```

Python 3.11 and 3.12 are supported. Set `OPENAI_API_KEY` only in the shell or a
secret manager; never commit credentials.

## 1+N Agent Architecture
The sizing layer uses 1 planner + N role workers:
- Planner agent:
  - Chooses which functional role should be tuned for each unsatisfied performance.
  - Dispatches a task containing full performance/spec context and role-local design variables.
- Worker agents (functional-role scoped):
  - Receive planner task.
  - Modify only their own role-local variables.
  - Propose expected impact on one or more role-affectable performances.

## 1+N Knowledge Base Architecture
The framework uses one planner KB and N worker KBs:
- Planner KB: maps performance targets to candidate functional roles.
- Worker KBs: role-specific tuning heuristics for selecting variables and step sizes.

Storage format:
- Runtime view layer: 3 JSON KB files (`*_kb_perf_tradeoff.json`, `*_kb_substruct_param_perf.json`,
  `*_kb_role_perf.json`).

## Iterative Sizing Loop
1. Initialization:
- `simulate_init` runs the real initialization pipeline when `--mode real`:
  - infer case paths from netlist name
  - generate `output/kb/<case>_design_specs.json` from settings
  - planner ranks roles and emits sequential worker instructions
  - workers assign initial role-scoped design-variable values
  - run simulation backend and append one record to `output/simulation_record.json`
- `state.specs` is mapped from extracted design specs.
- `state.functional_roles` is derived from tagging + role KB facts.

2. Planner dispatch (`planner_dispatch`):
- Reads latest committed simulation record from `output/simulation_record.json`.
- Uses design specs to evaluate unsatisfied metrics.
- Uses role/perf and perf/tradeoff KB facts to select:
  - one `target_metric`
  - one `selected_role_name`
  - one role-scoped `worker_instruction`
- Output is strict structured JSON.

3. Worker proposal (`worker_propose`):
- Retrieves only role-relevant tagging substructure + variable ownership.
- Retrieves role-variable bounds from settings.
- Uses latest committed record + current working state + selected improving-design slices (`latest 3 + best 3`).
- Uses full `kb_substruct_param_perf` facts.
- Returns:
  - updated role-owned variables
  - full absolute predicted performance vector (all metrics)
- Output is strict structured JSON.

4. Apply + completion check:
- `apply_update` enforces role scope guard and rejects out-of-scope updates.
- `check_completion` sets `force_simulation_commit=true` when:
  - all predicted specs are satisfied, or
  - planner-worker round count reaches `max_planner_worker_iter` (default 10).

5. Simulation commit:
- `simulate_commit` runs backend simulation and appends one record to `output/simulation_record.json`.
- `planner_worker_iter` resets to 0 after commit.

## Variable Scope Policy
Worker agents are strictly role-scoped:
- A worker can only touch design variables owned by its assigned role.
- Any out-of-scope update is rejected and logged.

## Simulation Commit Policy
Simulation commit is the only place where updates become authoritative:
- Predicted performances are provisional.
- KB updates happen only after simulation commit.

## Current Implementation Status
Current state:
- LangGraph state transition scaffold is implemented.
- LangGraph runs initialize + optimization loop (`load_input -> simulate_init -> select_unsat_perf -> ...`).
- `decompose_stage1`/`decompose_stage2` are removed from graph execution.
- `simulate_init` is planner-worker initialize pipeline in real mode by default.
- `simulate_init` and `simulate_commit` both append iter/parameters/performance to
  `output/simulation_record.json`.
- Iterative sizing nodes (`planner_dispatch -> worker_propose -> apply_update -> check_completion`)
  now use LLM structured outputs through `agentic_sizing.iteration`.
- Worker proposals are absolute-performance predictions (not deltas).
- Loop uses dual counters:
  - `iteration`: committed simulation round index
  - `planner_worker_iter`: in-round planner-worker proposal count
- Real Cadence simulation and deterministic mock backend are both supported.

This scaffold is intentionally minimal to stabilize interfaces and state flow before adding domain logic.
