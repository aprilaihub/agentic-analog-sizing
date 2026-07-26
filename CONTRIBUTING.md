# Contributing

Create a Python 3.11 or 3.12 virtual environment and install `.[dev,openai]`.
Before submitting a change, run:

```bash
ruff check src tests
ruff format --check src tests
mypy
pytest
python -m build
python scripts/check_release.py dist
```

Do not commit credentials, PDK/technology data, Cadence workspaces, generated
results, or third-party data without confirmed redistribution rights. New public
behavior requires tests and user-facing documentation.
