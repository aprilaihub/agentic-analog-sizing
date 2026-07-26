# Copilot instructions for agentic-sizing

## Project overview

`agentic-sizing` is an installable research package for LLM-assisted analog IC
sizing. The stable integration surface is `RunConfig`, `RunResult`, and
`run_sizing` from `agentic_sizing`.

## Architecture

- `workflow/`: LangGraph graph, routing, and nodes.
- `initialization/`: initial planner-worker flow and simulation helpers.
- `iteration/`: iterative planner-worker refinement and context construction.
- `simulator/`: simulator protocol, deterministic mock, and optional Cadence adapter.
- `llm/`: structured-LLM protocol and OpenAI implementation.
- `tagging/`, `kb/`, `specs/`: domain pipelines and JSON contracts.
- `resources/prompts/`: packaged prompt templates; load them through the resource loader.
- `core/models.py`: shared domain models and serialization helpers.
- `workflow/state.py`: workflow state and initial-state construction.

Keep runtime output outside `src/`. Do not add repository-relative resource reads,
`sys.path` edits, global environment mutation, Cadence workspaces, or generated
research artifacts to the package.

## Developer workflow

```bash
python -m pip install -e '.[dev]'
ruff check src tests
ruff format --check src tests
pytest
agentic-sizing run --help
```

Use `agentic-sizing tag` and `agentic-sizing extract-kb` for standalone tools.
Mock-mode tests must run without credentials, network access, or proprietary
software. Cadence integration must remain behind the simulator adapter boundary.

All LLM outputs must use structured schemas. Preserve published JSON shapes unless
a versioned migration is explicitly introduced. Add public type annotations and
tests for observable behavior rather than private implementation details.
