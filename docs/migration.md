# Migration to 0.1

Canonical modules now use snake case:

- `agentic_sizing.iterative_Sizing` → `agentic_sizing.iteration`
- `agentic_sizing.iterative_sizing` → `agentic_sizing.iteration`
- `agentic_sizing.optimizeGoal` → `agentic_sizing.specs`
- `agentic_sizing.optimize_goal` → `agentic_sizing.specs`
- `agentic_sizing.initialize` → `agentic_sizing.initialization`
- graph nodes now live under `agentic_sizing.workflow`
- planner/worker module filenames now use snake case

The duplicate compatibility packages were removed to keep the public source tree
unambiguous. Replace `python -m agentic_sizing.runner` with `agentic-sizing run`.
The corrected default record filename is
`output/simulation_record.json`. Explicit paths using the historical
`simulation_reocrd.json` spelling remain valid.

The historical `agenticSizing.agentic_sizing` namespace is no longer included;
use `agentic_sizing` directly. Set `AGENTIC_SIZING_PROJECT_ROOT` only for legacy
relative-path workflows; reusable code should pass explicit paths.
