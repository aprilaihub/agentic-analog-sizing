# agentic-sizing

`agentic-sizing` is a research package for LLM-assisted analog-circuit sizing.
It provides a LangGraph workflow, schema-constrained tagging and knowledge-base
tools, deterministic mock simulation, and optional OpenAI and Cadence integrations.

## Install and run

```bash
cd agentic-analog-sizing
python -m pip install -e .
```

Python 3.11 and 3.12 are supported.

Test the deterministic simulator without credentials:

```bash
python examples/mock_simulation.py
```

Run a credential-free workflow smoke test with mock simulation:

```bash
agentic-sizing run \
  --netlist input/tagging/5t_ota \
  --kb-root output/kb \
  --mode mock \
  --max-iter 0
```

## Python API

The same workflow can be called directly from Python or a notebook:

```python
from agentic_sizing import RunConfig, run_sizing

config = RunConfig(
    netlist_path="input/tagging/5t_ota",
    kb_root="output/kb",
    output_dir="output",
    mode="mock",
    max_iter=0,  # Credential-free initialization smoke test.
)

result = run_sizing(config)
print(result.termination_reason)
print(result.best_known_design_vars)
print(result.best_known_perfs)
print(result.simulation_record_path)
```

`RunConfig`, `RunResult`, and `run_sizing` are defined in
[`src/agentic_sizing/api.py`](src/agentic_sizing/api.py) and re-exported from
`agentic_sizing`, so users should import them as shown above. `run_sizing` also
accepts optional `simulator=` and `llm_client=` implementations for custom
research backends. See [`docs/api.md`](docs/api.md) for the supported API surface.

For real Cadence simulation, install the optional dependencies and set the
required paths before running:

```bash
python -m pip install -e '.[openai,cadence]'

# Enter the key without writing it into the repository or shell history.
read -rsp "OpenAI API key: " OPENAI_API_KEY
export OPENAI_API_KEY

# Original Cadence project containing cds.lib and the referenced libraries.
export CADENCE_PROJECT_DIR=/path/to/cadence-project

# Writable location for generated simulation workspaces.
export AGENTIC_SIZING_CADENCE_WORK_ROOT=/path/to/cadence-workspaces

test -f "$CADENCE_PROJECT_DIR/cds.lib"

agentic-sizing run \
  --netlist input/tagging/5t_ota \
  --kb-root output/kb \
  --mode real \
  --max-iter 5
```

The YAML loader substitutes `${CADENCE_PROJECT_DIR}` automatically. If
`AGENTIC_SIZING_CADENCE_WORK_ROOT` is omitted, generated workspaces default to
`output/cadence_workspaces`.

The `cadence` extra does not install Cadence itself; a licensed Virtuoso/Maestro
installation must already be available. Run `agentic-sizing run --help` for all
options. The Python API exposes `RunConfig` and `run_sizing`; see `docs/api.md`.

### Run defaults

Only `--netlist` and `--kb-root` are required. Unspecified options use:

| Option | Default |
|---|---|
| `--mode` | `real` |
| `--max-iter` | `400` |
| `--max-stagnation` | `500` |
| `--max-runtime-seconds` | `0` (no time limit) |
| `--max-planner-worker-iter` | `2` |
| `--simulation-record-path` | `output/simulation_record.json` |
| `--initial-sample-count` | `1` |
| KB input | enabled; disable with `--disable-kb-input` |
| Critical heuristics | enabled; disable with `--disable-heuristics` |
| Continue after meeting specs | disabled; enable with `--continue-after-specs` |
| Include history in CLI output | disabled; enable with `--show-history` |


## Other tools

```bash
agentic-sizing tag --help
agentic-sizing extract-kb --help
```

Cadence is optional and no licensed technology data is distributed. Users must
provide a local Cadence installation, settings, and project template. The large
simulation workspaces in the development checkout are explicitly excluded from
packages and source distributions.

## Reproducibility and data contracts

Prompts and JSON schemas ship as package data. Small examples live under
`examples/`, while public netlist, settings, and improving-design fixtures live
under `input/`. Runtime records and simulator outputs belong in ignored output
directories. Randomized built-in strategies use documented deterministic seeds.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md), [docs/architecture.md](docs/architecture.md),
[docs/api.md](docs/api.md), and [docs/migration.md](docs/migration.md). Licensed
under the MIT License.
