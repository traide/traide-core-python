# Traide Core Python

A Python library for core Traide functionality including observability utilities.

## Installation

### Core Installation

This package can be installed from GitHub:

```bash
uv add git+https://github.com/traide/traide-core-python.git
```

Or add it to your `pyproject.toml`:

```toml
[dependencies]
traide-core-python = {git = "https://github.com/traide/traide-core-python.git"}
```

### Optional Extras

The package supports optional extras for framework-specific integrations:

**FastAPI support:**
```bash
uv add "traide-core-python[fastapi]@git+https://github.com/traide/traide-core-python.git"
```

Or in `pyproject.toml`:
```toml
[dependencies]
traide-core-python = {git = "https://github.com/traide/traide-core-python.git", extras = ["fastapi"]}
```

**FastStream support:**
```bash
uv add "traide-core-python[faststream]@git+https://github.com/traide/traide-core-python.git"
```

Or in `pyproject.toml`:
```toml
[dependencies]
traide-core-python = {git = "https://github.com/traide/traide-core-python.git", extras = ["faststream"]}
```

## Usage

```python
from traide.observability.tracing_config import configure_tracing, TracingType
from traide.observability.logging_config import LoggingConfig, LogType, LogLevel
from traide.observability.sentry_config import SentryConfig, configure_sentry

# Or import everything from observability
from traide.observability import configure_tracing, LoggingConfig, SentryConfig
```

## Development

Install development dependencies:

```bash
uv sync --extra dev
```

Install pre-commit hooks:

```bash
uv run pre-commit install
```

Run all checks:

```bash
uv run pre-commit run --all-files
```

Run tests:

```bash
uv run pytest
```
