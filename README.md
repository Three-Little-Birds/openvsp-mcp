# openvsp-mcp · Hands-On VSP Automation for Everyone

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-brightgreen.svg)](pyproject.toml)
[![CI](https://github.com/Three-Little-Birds/openvsp-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Three-Little-Birds/openvsp-mcp/actions/workflows/ci.yml)

This package shows how to teach an MCP agent to edit [OpenVSP](https://openvsp.org/) designs, run [VSPAero](https://openvsp.org/vspaero) analyses, and collect aerodynamic metrics in a repeatable way. Think of it as a tutorial that replaces brittle `.vspscript` snippets with clean Python models.

## Learning outcomes

- Install and configure OpenVSP/VSPAero for scripted use.
- Generate and run your first `.vspscript` file directly from Python.
- Wire the python-sdk tool so an agent can tweak geometry parameters (“add 10% span” or “rerun VSPAero at 80 m/s”).

## Before you start

| Requirement | Notes |
| ----------- | ----- |
| OpenVSP 3.38+ | Download from [openvsp.org](https://openvsp.org/download/) and make `vsp` available on `PATH`. |
| VSPAero | Ships with OpenVSP; ensure `vspaero` can run from the terminal. |
| Python 3.10+ + `uv` | Used to install dependencies and run examples. |

Optional: install `paraview` or the OpenVSP GUI if you want to visualise the geometry after each run.

## Step 1 – Install the wrapper

```bash
uv pip install "git+https://github.com/Three-Little-Birds/openvsp-mcp.git"
```

Set `OPENVSP_BIN` or `VSPAERO_BIN` if the executables are not on `PATH`.

## Step 2 – Script your first geometry change

```python
from pathlib import Path

from openvsp_mcp import GeometryRequest, run_geometry_edit

request = GeometryRequest(
    source_vsp3="baseline.vsp3",
    wing_span_scale=1.1,     # +10% span
    wing_twist_delta_deg=2.0,
)

response = run_geometry_edit(request)
print("Edited file:", response.output_vsp3)
print("Script written to:", response.script_path)
```

Open the resulting `.vsp3` in the GUI to confirm the change. The response also stores the generated `.vspscript` so you can audit every command that was executed.

## Step 3 – Add an aerodynamic sweep with VSPAero

```python
from openvsp_mcp import AeroRequest, run_aero_analysis

aero = AeroRequest(
    source_vsp3=response.output_vsp3,
    alpha_start_deg=-2,
    alpha_end_deg=12,
    alpha_step_deg=2,
    mach=0.12,
    reference_velocity_m_s=70.0,
)

aero_response = run_aero_analysis(aero)
print("ADB output:", aero_response.adb_path)
print("CSV summary:", aero_response.csv_path)
```

Load the CSV into a notebook to plot lift/drag or inspect convergence metrics.

## Step 4 – Let an MCP agent drive the workflow

### FastAPI microservice

```python
from openvsp_mcp.fastapi_app import create_app

app = create_app()
```

Launch the docs:

```bash
uv run uvicorn openvsp_mcp.fastapi_app:create_app --factory --port 8002
```

Use the Swagger UI to try `/geometry` and `/aero` endpoints interactively.

### python-sdk tool

```python
from mcp.server.fastmcp import FastMCP
from openvsp_mcp.tool import build_tool

mcp = FastMCP("openvsp-mcp", "OpenVSP automation")
build_tool(mcp)

if __name__ == "__main__":
    mcp.run()
```

In your MCP client, call `openvsp-mcp.geometry` with a set of wing modifiers, then chain `openvsp-mcp.vspaero` to fetch aerodynamic coefficients.

## Stretch exercises

- **Parameter sweep:** loop over a dictionary of span/twist changes and chart the resulting lift curve slope.
- **Geometry morphing:** feed the tool a series of fuselage length adjustments and generate a GIF from the saved `.vsp3` files.
- **Design review:** archive the generated `.vspscript` files alongside optimisation runs so teammates can reproduce results.

## Developing the package

```bash
uv pip install --system -e .[dev]
uv run ruff check .
uv run pytest
```

Tests mock the CLI to demonstrate the expected inputs/outputs before you work with real binaries.

## License

MIT — see [LICENSE](LICENSE).
