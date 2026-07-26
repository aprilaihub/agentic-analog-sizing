# Environment Setup

This project provides a reproducible environment file at:
- `environment.yml`

## Option A: Conda (recommended)

```bash
cd .
conda env create -f environment.yml
conda activate agentic-sizing
```

## Option B: One-command venv bootstrap

```bash
cd .
bash scripts/bootstrap_env.sh
```

Then activate:

```bash
source .venv/bin/activate
```

## Verify environment and run tests

```bash
cd .
bash scripts/verify_env.sh
```

This verifies required modules (`langgraph`, `openai`, `typing_extensions`) and runs:

```bash
pytest
```

Note:
- If you run tagging with OpenAI, set `OPENAI_API_KEY` in your shell. Never commit `.env.local`.
