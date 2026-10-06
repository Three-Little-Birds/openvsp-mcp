# openvsp-mcp

Create and inspect parametric aircraft geometry through the Model Context Protocol.
The same tools work over local stdio or Streamable HTTP.

## Aircraft construction

`openvsp_create_aircraft` builds a conventional aircraft from typed dimensions:

- Fuselage length and three equal elliptical interior cross sections.
- A single trapezoidal wing, horizontal tail, and upright vertical tail.
- Span, root/tip chord, location, quarter-chord sweep, dihedral, incidence, tip twist, and symmetric four-series airfoil thickness.
- Explicit input units (`m` or `ft`), with output geometry and constraints in SI.
- Native saved-parameter checks and optional bounds on span, projected span, area, aspect ratio, taper, root/tip chord, fuselage length, and complete-aircraft bounding extents.

The tool saves a unique run directory containing the `.vsp3` model, generated
AngelScript, request specification, validation report, and process logs. Existing
models are not overwritten by aircraft creation.

This is a geometry builder. Its checks do not establish aerodynamic stability,
component clearance, structural feasibility, or a watertight analysis mesh.

## Install

Install [OpenVSP](https://openvsp.org/download.php), then install this package in a
Python 3.10+ environment:

```bash
uv venv
uv pip install -e '.[dev]'
export OPENVSP_BIN=/absolute/path/to/OpenVSP/vsp
export VSPAERO_BIN=/absolute/path/to/OpenVSP/vspaero  # optional standalone solver
export OPENVSP_OUTPUT_DIR=/absolute/path/to/artifacts
```

OpenVSP is executed as a separate process; its Python bindings are not required.
The package pins `mcp>=1.20,<2` because it uses the SDK's FastMCP API.
MCP 2.x requires a separate migration.

Build the included dimensioned example:

```bash
uv run python examples/create_aircraft.py
```

See [examples/conventional_aircraft.json](examples/conventional_aircraft.json) for
the complete request, including its constraint bounds. From Python:

```python
from pathlib import Path
from openvsp_mcp import AircraftCreateRequest, create_aircraft

request = AircraftCreateRequest.model_validate_json(
    Path("examples/conventional_aircraft.json").read_text()
)
response = create_aircraft(request)
print(response.geometry_path)
print(response.validation_passed)
print([check for check in response.checks if not check.passed])
```

A conflicting constraint returns `validation_passed=false` with the actual value
and bound; it retains the model for review. Invalid requests or native execution
failures return errors. The server does not silently resize geometry or relax
constraints.

## Sizing and typed revisions

`openvsp_plan_aircraft` solves a bounded wing sizing problem without running
OpenVSP or writing files. Start with a complete conventional-aircraft specification;
only explicitly listed `wing.span`, `wing.root_chord`, and `wing.tip_chord` may change.
All other dimensions and angles remain fixed. Adjustable bounds use the aircraft's
input units; sizing targets and constraint bounds use SI.

For example, to keep a 4 m developed span and size the chords for a 2 m² wing with
taper 0.5:

```python
from openvsp_mcp import AircraftPlanRequest, plan_aircraft

plan = plan_aircraft(
    AircraftPlanRequest(
        aircraft=request.aircraft,
        adjustable=[
            {"parameter": "wing.root_chord", "minimum": 0.2, "maximum": 1.0},
            {"parameter": "wing.tip_chord", "minimum": 0.1, "maximum": 0.8},
        ],
        targets={"span_m": 4.0, "area_m2": 2.0, "taper_ratio": 0.5},
    )
)
if plan.status == "ready":
    response = create_aircraft(plan.create_request)
else:
    print(plan.diagnostics)
```

Here the root and tip chords become approximately 0.667 m and 0.333 m. The planner
uses developed area and the native projected-span aspect-ratio convention. It
handles simultaneous span, projected span, area, aspect ratio, taper, chord bounds,
and fixed fuselage-length constraints. Conflicting requirements return
`status="infeasible"` with diagnostics. Numerical precision failures return
`status="unresolved"` without claiming the requirements are impossible.
Whole-aircraft bounding extents are marked
`deferred`: `ready` means analytically feasible, and native validation is still
required. Every exact target and adjustable bound is included in `create_request`
for verification after construction.

If multiple solutions exist, the planner selects the feasible span closest to the
baseline, then the closest chord sum, then the chord split minimizing squared
changes. It reports this policy as an assumption; it does not claim aerodynamic
optimization or choose unlisted variables.

`openvsp_update_aircraft` rebuilds typed changes from a managed candidate into a
new run. Use its saved `report.json` as the source:

```python
from openvsp_mcp import AircraftRevisionRequest, revise_aircraft

revised = revise_aircraft(
    AircraftRevisionRequest(
        source_report_path=response.report_path,
        changes=[{"parameter": "wing.sweep_deg", "value": 12.0}],
    )
)
print(revised.parent_candidate_id, revised.candidate_id)
print(revised.validation_passed)
```

Lengths retain the parent's units; angles use degrees. Constraints and validation
tolerances are inherited. Passing `constraints=[]` explicitly clears constraints;
passing a list replaces them. A candidate with failed constraints may be revised.
Source model/specification hashes are checked before rebuilding, and the child
report records parent identity, hashes, and parameter changes. These hashes detect
snapshot drift; they are not authentication. Keep the model, specification, and
report together when relocating a bundle. Older bundles lacking integrity metadata
must be rebuilt. Native component IDs may change during reconstruction.

Run the complete failing-candidate → plan → typed-repair example:

```bash
uv run python examples/plan_and_revise.py
```

## Dimension conventions

All input length fields share `aircraft.units`. Constraint metric suffixes
`_m` and `_m2` always mean metres and square metres, even for inputs in feet.

| Quantity | Convention |
|---|---|
| Wing and horizontal-tail span | Full developed span, including both mirrored halves |
| Vertical-tail span | One-sided root-to-tip height; no mirrored second fin |
| `x_le`, `z` | Root leading edge from the fuselage nose; X aft, Z up |
| `sweep_deg` | Quarter-chord sweep |
| `incidence_deg` | Root twist about the leading edge |
| `tip_twist_deg` | Tip twist relative to root incidence |
| `thickness_ratio` | Symmetric NACA four-series thickness/chord at both stations |
| Fuselage width/height | Cross-section dimensions at 25%, 50%, and 75% length |
| `wing_aspect_ratio` | OpenVSP TotalAR: projected span squared / developed planform area |
| `wing_taper_ratio` | Tip chord / root chord |
| `aircraft_*_extent_m` | Union of native component bounding boxes, including thickness and placement |

The airfoil family, fuselage station layout, and other assumptions are included
in every report. Stored dimensions are compared against requested values using
`absolute_tolerance + relative_tolerance * abs(target)`. User-supplied constraint
bounds are inclusive, permitting only floating-point roundoff within eight ULPs
of the measured value or bound, rather than the dimensional tolerance above.

## MCP service

```bash
uv run openvsp-mcp                           # stdio
uv run openvsp-mcp --describe                # schemas and annotations
uv run openvsp-mcp --transport streamable-http --host 127.0.0.1 --port 8000 --path /mcp
```

| Tool | Behavior |
|---|---|
| `openvsp_create_aircraft` | Create and verify a new dimensioned conventional aircraft |
| `openvsp_plan_aircraft` | Solve bounded wing sizing analytically; return a build request or infeasibility diagnostics |
| `openvsp_update_aircraft` | Rebuild typed changes into a new candidate, preserving and verifying the parent snapshot |
| `openvsp.inspect` | Read component IDs and saved native parameters; no binary execution or model writes |
| `openvsp.modify` | Apply trusted raw AngelScript commands to an existing model in place |
| `openvsp.run_vspaero` | Apply raw edits, then run a preconfigured standalone VSPAero case |

MCP tool arguments are nested under `request`. For example, pass the contents of
the example JSON as `{"request": <example contents>}` to `openvsp_create_aircraft`.
Responses include structured content and output schemas, with explicit read/write
annotations. Legacy dotted tool names remain available.

### Claude Desktop

Configure a local stdio server using the installed environment's absolute Python
path. See Anthropic's [local MCP documentation](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

```json
{
  "mcpServers": {
    "openvsp": {
      "command": "/absolute/path/to/openvsp-mcp/.venv/bin/python",
      "args": ["-m", "openvsp_mcp"],
      "env": {
        "OPENVSP_BIN": "/absolute/path/to/OpenVSP/vsp",
        "OPENVSP_OUTPUT_DIR": "/absolute/path/to/artifacts"
      }
    }
  }
}
```

### ChatGPT and remote Claude connections

ChatGPT supports custom MCP servers over streaming HTTP or SSE, with public
HTTPS endpoints or [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
See OpenAI's [custom MCP server guide](https://developers.openai.com/api/docs/guides/custom-mcp-server).
Anthropic's [remote connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
explains its cloud-origin connections and endpoint reachability requirements.

Keep OpenVSP on the machine running the server. The HTTP bind defaults to
loopback. If a reverse proxy preserves its public Host header, explicitly allow it:

```bash
uv run openvsp-mcp --transport streamable-http --allowed-host vsp.example.com
```

Use `--allowed-origin https://vsp.example.com` when a browser sends that Origin.
These flags preserve Host/Origin validation; they do not provide authentication.
The existing raw-script tools execute caller-provided code with server privileges,
so use this server with trusted clients and authenticated ingress.
OAuth, public deployment, and account connections are not configured by this package.

Paths in responses belong to the server filesystem. They are not automatically
downloadable from a cloud chat. Remote artifact delivery requires an authenticated
file endpoint or an MCP resource integration.

## Agent workflow

1. Extract the aircraft dimensions, units, hard constraints, and permitted design
   variables. Obtain a complete baseline specification and record shape assumptions.
2. Call `openvsp_plan_aircraft` when wing sizing is needed. Inspect diagnostics and
   deferred checks; never treat `ready` as a native validation pass.
3. Pass `plan.create_request` to `openvsp_create_aircraft`. Read
   `validation_passed`, actual measurements, and every failed check.
4. For further changes, use `openvsp_update_aircraft` with the saved report and
   explicit parameter replacements. When applying planner changes to a parent,
   also pass `plan.create_request.constraints` to preserve sizing targets and bounds.
5. Return the final model and report. Report which geometry checks passed; keep
   aerodynamic and structural claims separate.

The server sizes, builds, and measures each candidate deterministically. The client
model maps requirements, selects permitted variables, and controls iteration.
No provider API key is needed by this server.

## REST surface

```bash
uv run uvicorn openvsp_mcp.fastapi_app:create_app --factory --host 127.0.0.1 --port 8002
```

`POST /vsp/aircraft`, `POST /vsp/aircraft/plan`, `POST /vsp/aircraft/revise`,
`POST /vsp/inspect`, `POST /vsp/modify`, and `POST /vsp/run`
accept the corresponding request models. These REST routes are separate from the
MCP `/mcp` endpoint.

## Raw edits and VSPAero

Raw edits retain a script, model snapshot, request, and logs. Only a completed
native run replaces the input model. OpenVSP API errors, missing completion,
invalid output, and timeouts are surfaced concretely. Relative file references
inside custom commands resolve from that run's artifact directory.

For `run_vspaero`, `case_name` is a case-base path without a suffix. The standalone
solver requires a matching `.vspaero` input and prepared mesh. The caller must
prepare a mesh consistent with the edited geometry; this tool does not generate
or verify that mesh. A `.vsp3` alone is not a solver case.

## Development and validation

```bash
uv run ruff check .
uv run pytest
OPENVSP_BIN=/absolute/path/to/vsp uv run pytest  # also run native integration tests
```

Tests cover strict dimensions and units, projected-span conventions, constraint
failure, read-only inspection, retained artifacts, failed-edit recovery, timeouts,
and MCP initialize/list/call exchanges over stdio and Streamable HTTP.
Native tests construct metric and imperial variants and verify the saved model.
Protocol tests do not constitute end-to-end testing inside Claude or ChatGPT.

See [docs/contribution-roadmap.md](docs/contribution-roadmap.md) for the next
contribution stages. Include reproducible specifications and native reports in
geometry-related PRs.

MIT license for this wrapper. OpenVSP binaries have their own license; see the
[OpenVSP license](https://openvsp.org/license.php) before redistribution.
