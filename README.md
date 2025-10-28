# openvsp-mcp

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-brightgreen.svg)](pyproject.toml)
[![CI](https://github.com/yevheniikravchuk/openvsp-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/yevheniikravchuk/openvsp-mcp/actions/workflows/ci.yml)

Model Context Protocol tooling for automating [OpenVSP](https://openvsp.org/) geometry edits and [VSPAero](https://openvsp.org/vspaero) runs. It bundles the scripting glue—`.vspscript` generation, CLI execution, response parsing—so agents can drive geometry changes and aerodynamics batches without hand-maintaining shell wrappers.

## Why you might want this

- **Batch geometry tweaks** – adjust span, sweep, twist, etc. from an automated workflow and inspect the generated `.vspscript` for peer review.
- **Chain into VSPAero** – the same request can trigger a [VSPAero](https://openvsp.org/vspaero) run and return the `.adb` output so optimisation loops can proceed.
- **Leave an audit trail** – responses include script locations and case names, making it easy to archive or replay studies.

## Features

- Declarative request/response models for geometry edits and optional VSPAero sweeps.
- Subprocess helpers that write `.vspscript` automation files and invoke `vsp` / `vspaero` binaries.
- FastAPI app factory and python-sdk tool registration helper.
- 100% MIT-licensed and covered by unit tests.

## Installation

```bash
pip install "git+https://github.com/yevheniikravchuk/openvsp-mcp.git"
```

## Quickstart (FastAPI)

```python
from openvsp_mcp.fastapi_app import create_app

app = create_app()
```

Launch locally:

```bash
uv run uvicorn openvsp_mcp.fastapi_app:create_app --factory --host 127.0.0.1 --port 8002
```

## Quickstart (python-sdk tool)

```python
from mcp.server.fastmcp import FastMCP
from openvsp_mcp.tool import build_tool

app = FastMCP("openvsp-mcp", "OpenVSP automation")
build_tool(app)

if __name__ == "__main__":
    app.run()
```

### Example STDIO session

```bash
uv run mcp dev examples/openvsp_tool.py
```

Send a JSON request:

```json
{
  "tool": "openvsp-mcp.vsp",
  "arguments": {
    "geometry_file": "models/demo.vsp3",
    "set_commands": [{ "command": "vsp_set wing Span 0.5" }],
    "run_vspaero": true,
    "case_name": "hover"
  }
}
```

## Environment variables

- `OPENVSP_BIN` (default `vsp`)
- `VSPAERO_BIN` (default `vspaero`)

## Local development

```bash
uv pip install --system -e .[dev]
uv run ruff check .
uv run pytest
```

Tests use mocked OpenVSP/VSPAero calls so newcomers can see the minimum payload without installing the solvers.

## License

MIT — see [LICENSE](LICENSE).
