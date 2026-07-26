# Developer architecture

The package is organized by responsibility:

```text
agentic_sizing/
├── api.py, cli.py              # public API and command line
├── core/                       # shared metric and operating-region logic
├── initialization/             # initial design generation and simulation
├── iteration/                  # planner/worker refinement loop
│   └── context/                # context builders, data, and summaries
├── workflow/                   # execution, state, graph, routing, and nodes
├── simulator/                  # simulator protocol, mock, and Cadence adapter
├── kb/, tagging/, specs/       # domain workflows and contracts
├── llm/                        # structured-LLM boundary
└── resources/                  # packaged prompts loaded with importlib.resources
```

Keep dependencies directed inward: CLI and workflow code may depend on domain
packages; domain packages may depend on `core`, `types`, and simulator/LLM
protocols. Core code must not import the CLI or workflow. New simulator and LLM
implementations should satisfy the public protocols instead of being embedded in
workflow nodes.

Use `RunConfig` and `run_sizing` as the stable integration surface. Treat files
inside `workflow/nodes`, initialization support helpers, and iteration context as
implementation details. Prompts and schemas are package data and must not be
opened through repository-relative paths.
