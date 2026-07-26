# Simulator integration

The stable simulator boundary is `SimulationAdapter`. Use
`MockSimulationAdapter` for deterministic, credential-free tests and
`CadenceSimulationAdapter` for a user-supplied Cadence project.

```python
from agentic_sizing.simulator import CadenceSimulationAdapter

simulator = CadenceSimulationAdapter(
    settings_path="/path/to/case.yaml",
    design_var_order=["l1", "w1", "ibias"],
    perf_order=["gain", "ugb", "power"],
)
result = simulator.simulate({"l1": 1e-6, "w1": 10e-6, "ibias": 5e-6})
```

The case YAML must define `ocn_script`, `des_vars`, `responses`, `outputs`,
`options`, and `objective`; see `src/agentic_sizing/specs/opt_settings.schema.json`.
Set `${CADENCE_PROJECT_DIR}` externally and configure
`AGENTIC_SIZING_CADENCE_WORK_ROOT` for generated workspaces. Cadence itself,
technology files, libraries, and project templates are not distributed.

Real runs require the `virtuoso` executable in `PATH`. Generated SKILL files,
CSV results, logs, and simulation workspaces belong under ignored runtime
directories, never under `src/agentic_sizing`.
