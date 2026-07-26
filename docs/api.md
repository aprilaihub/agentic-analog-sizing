# Public API

The supported library surface is exported from `agentic_sizing`:

- `RunConfig` and `RunResult` describe workflow inputs and outputs.
- `run_sizing` runs the graph and accepts optional simulator and LLM clients.
- `SimulationAdapter` and `StructuredLLMClient` are structural protocols.
- `MockSimulationAdapter` is deterministic and has no external-tool dependency.

Backend implementations should return metric dictionaries with stable metric names.
Callers own their input and output paths; library code does not require a checkout-
relative working directory. Internal graph nodes and prompt helpers may change
between minor releases until promoted into this public surface.

## Optional integrations

Install `[openai]` for the bundled structured OpenAI client or `[cadence]` for
the Cadence adapter. Cadence
settings must reference resources supplied and licensed by the user.
