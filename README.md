# openvsp-mcp - Parametric geometry for MCP workflows

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg" alt="Python 3.10 or newer"></a>
  <a href="https://github.com/Three-Little-Birds/openvsp-mcp/actions/workflows/ci.yml"><img src="https://github.com/Three-Little-Birds/openvsp-mcp/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <img src="https://img.shields.io/badge/status-stable-4caf50.svg" alt="Project status: stable">
  <img src="https://img.shields.io/badge/MCP-tooling-blueviolet.svg" alt="MCP tooling badge">
</p>

> **TL;DR**: Automate [OpenVSP](https://openvsp.org/) geometry edits and VSPAero runs so agents can generate meshes, scripts, and aerodynamic coefficients without manual GUI steps.

## Table of contents

1. [Why agents love it](#why-agents-love-it)
2. [Quickstart](#quickstart)
3. [Run as a service](#run-as-a-service)
4. [Agent playbook](#agent-playbook)
5. [Stretch ideas](#stretch-ideas)
6. [Accessibility & upkeep](#accessibility--upkeep)
7. [Contributing](#contributing)

## Why agents love it

| Persona | Immediate win | Scales because... |
|---------|----------------|-----------------
| **New users** | One command produces a `.vsp3` copy, applies scripted tweaks, and runs VSPAero - no CAD background required. | The wrapper ships ready-made examples, typed requests, and clean output folders, aligning with modern README guidance on "show, don't tell." |
| **Experienced teams** | Expose OpenVSP/VSPAero functionality to MCP agents over REST or STDIO. | Deterministic logs (`stdout.log`, `vspaero_metrics.json`) make it drop-in for CI, optimisation loops, and audit trails.

## Quickstart

### 1. Install the package

```bash
uv pip install "git+https://github.com/Three-Little-Birds/openvsp-mcp.git"
```

Ensure `vsp` and `vspaero` are reachable. If not:

```bash
export OPENVSP_BIN=/Applications/OpenVSP/vsp
export VSPAERO_BIN=/Applications/OpenVSP/vspaero
```

### 2. Run a scripted geometry edit

```python
from openvsp_mcp import OpenVSPRequest, execute_openvsp

request = OpenVSPRequest(
    geometry_file="examples/blended_wing.vsp3",
    set_commands=["SetParmVal( 'WingGeom', 'X_Root', 'Design', 3.0 )"],
    run_vspaero=True,
    case_name="wing_trim",
)
response = execute_openvsp(request)
print("Outputs live in", response.output_dir)
```

`response` includes the updated `.vsp3`, the command script, and VSPAero CSVs for immediate plotting.

## Run as a service

### CLI (STDIO transport)

```bash
uvx openvsp-mcp  # runs the MCP over stdio
# or python -m openvsp_mcp
```

Use `python -m openvsp_mcp --describe` to inspect metadata without starting the server.

### FastAPI (REST)

```bash
uv run uvicorn openvsp_mcp.fastapi_app:create_app --factory --port 8002
```

Upload a `.vsp3` and JSON request at `http://127.0.0.1:8002/docs`.

### python-sdk tool (STDIO / MCP)

```python
from mcp.server.fastmcp import FastMCP
from openvsp_mcp.tool import build_tool

mcp = FastMCP("openvsp-mcp", "OpenVSP automation")
build_tool(mcp)

if __name__ == "__main__":
    mcp.run()
```

Then launch with `uv run mcp dev examples/openvsp_tool.py` and connect your agent.

## Agent playbook

- **Geometry studies** - script sweep operations (span, twist, control surface deflections) and archive each variant.
- **Aerodynamic coefficients** - hand VSPAero results to `ctrltest-mcp` or custom controllers.
- **Mesh exports** - agents can request STL/OBJ assets for CFD or manufacturing pipelines.

## Stretch ideas

1. Pair with `foam-agent-mcp-core` to auto-generate mesh-ready cases.
2. Use deck.gl to visualise planform edits by surfacing geometry metadata in the response.
3. Schedule nightly configuration sweeps (span x sweep x incidence) and store the results for design-of-experiments studies.

## Accessibility & upkeep

- Badges contain alt text and are limited for readability, keeping with modern README guidance.
- Run `uv run pytest` before committing; tests mock VSPAero calls so they finish quickly.
- Keep OpenVSP/VSPAero versions consistent across developers to avoid geometry mismatches.

## Contributing

1. `uv pip install --system -e .[dev]`
2. Run `uv run ruff check .` and `uv run pytest`
3. Submit PRs with sample scripts or geometry diffs so reviewers can validate quickly.

MIT license - see [LICENSE](LICENSE).
