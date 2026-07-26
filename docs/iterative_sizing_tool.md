# Iterative Sizing Tool (LangGraph Runtime)

This document describes the LLM-based iterative sizing stage integrated into the existing LangGraph nodes:

- `planner_dispatch`
- `worker_propose`
- `apply_update`
- `check_completion`

The graph node names are unchanged.

## Runtime Flow

1. `planner_dispatch`
- Reads latest committed record from `output/simulation_record.json`.
- Evaluates unsatisfied specs using `output/kb/<case>_design_specs.json`.
- Uses:
  - `output/kb/<case>_kb_role_perf.json`
  - `output/kb/<case>_kb_perf_tradeoff.json`
- Selects one target metric + one role + one worker instruction.

2. `worker_propose`
- Retrieves role-local data from `output/tagging/<case>.tagging.json`.
- Retrieves bounds from `input/kb/<case>_settings.json`.
- Retrieves latest committed record from `output/simulation_record.json`.
- Retrieves improving-design slices from `input/kb/<case>_improving_designs.json` (`latest 3 + best 3`).
- Retrieves full `output/kb/<case>_kb_substruct_param_perf.json`.
- Returns role-scoped variable updates + full predicted performances.

3. `apply_update`
- Applies only role-owned variable writes.
- Rejects out-of-scope updates.
- Updates working predicted performance vector.
- Increments `planner_worker_iter` by 1.

4. `check_completion`
- Re-checks predicted spec satisfaction.
- Forces simulation commit when either condition is true:
  - all predicted specs satisfied
  - `planner_worker_iter >= max_planner_worker_iter` (default 10)

5. `simulate_commit`
- Runs simulation backend (`real` Cadence or `mock`).
- Appends one record to `output/simulation_record.json`.
- Resets `planner_worker_iter` to 0.

## Structured Output Contracts

## Planner Output

```json
{
  "target_metric": "cmrr",
  "selected_role_name": "Main signal path",
  "worker_instruction": "...",
  "selection_rationale": "...",
  "focus_kb_evidence": ["..."]
}
```

Validation:
- `target_metric` must be in current unsatisfied metrics.
- `selected_role_name` must be a role from tagging stage1.

## Worker Output

```json
{
  "role_name": "Main signal path",
  "target_metric": "cmrr",
  "updated_design_vars": [
    {"name": "l2", "value": 1.2e-6, "reason": "..."}
  ],
  "predicted_performances": [
    {"name": "cmrr", "value": 82.0, "reason": "..."}
  ],
  "rationale": "..."
}
```

Validation:
- Updated vars must exactly cover role-owned variables and stay in bounds.
- Predicted performances must exactly cover all spec metrics.

## Counters and Termination

- `iteration`: committed simulation round index (aligned with `simulation_reocrd.json`).
- `planner_worker_iter`: proposal count inside current simulation round.
- `max_iter`: simulation-round cap (not worker-step cap), default `500`.
- `max_planner_worker_iter`: worker-step cap before forced commit (default 10).

## Run Example (mock simulation backend)

```bash
cd agentic-analog-sizing
agentic-sizing run \
  --netlist input/tagging/5t_ota \
  --kb-root output/kb \
  --mode mock \
  --max-planner-worker-iter 10 \
  --simulation-record-path output/simulation_record.json \
  --show-history
```

## Notes

- LLM provider currently uses OpenAI structured output.
- `OPENAI_API_KEY` must be configured for real initialize/iterative LLM calls.
- No default temp file output is used in iterative sizing (in-memory context path).
