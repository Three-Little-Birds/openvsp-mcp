"""MCP tools shared by local and remote clients."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .aircraft import create_aircraft
from .core import execute_openvsp
from .describe import describe_geometry
from .models import (
    AircraftCreateRequest,
    AircraftCreateResponse,
    AircraftPlanRequest,
    AircraftPlanResponse,
    AircraftRevisionRequest,
    AircraftRevisionResponse,
    OpenVSPGeometryRequest,
    OpenVSPInspectResponse,
    OpenVSPRequest,
    OpenVSPResponse,
)
from .planning import plan_aircraft
from .revisions import revise_aircraft


def build_tool(app: FastMCP) -> None:
    """Register aircraft planning, construction, revision, and low-level tools."""

    @app.tool(
        name="openvsp_plan_aircraft",
        description=(
            "Plan a bounded conventional aircraft wing without invoking OpenVSP or writing files. "
            "Supply a complete baseline aircraft; every field remains fixed unless wing.span, "
            "wing.root_chord, or wing.tip_chord is explicitly listed in adjustable. Adjustable "
            "bounds use aircraft.units (m or ft); targets and constraints use SI. Horizontal span "
            "is full developed span; projected span includes dihedral. Aspect ratio follows "
            "OpenVSP: projected span squared divided by developed area. Explicit targets are "
            "exact requirements. Returns ready with a create_request, or infeasible diagnostics; "
            "aircraft extent checks remain deferred until a native build. Pass a ready "
            "create_request to openvsp_create_aircraft and read its native checks."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    def plan(request: AircraftPlanRequest) -> AircraftPlanResponse:
        return plan_aircraft(request)

    @app.tool(
        name="openvsp_create_aircraft",
        description=(
            "Create a new conventional aircraft from explicit fuselage, wing, horizontal-tail, "
            "and vertical-tail dimensions, without raw scripts. Input lengths use aircraft.units "
            "(m or ft); saved model and constraints use SI. Horizontal spans are full developed "
            "spans; vertical-tail span is root-to-tip height. Sweep is quarter-chord, in degrees. "
            "Returns retained .vsp3, script, specification, native measurements, and checks. "
            "Read validation_passed and failed checks before claiming constraints are satisfied. "
            "Aerodynamic stability, collision clearance, and watertightness are not checked."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
    )
    def build_aircraft(request: AircraftCreateRequest) -> AircraftCreateResponse:
        return create_aircraft(request)

    @app.tool(
        name="openvsp_update_aircraft",
        description=(
            "Revise a managed aircraft using typed parameter changes and build a new immutable "
            "candidate. Supply source_report_path from a current create/revision run; sibling "
            "specification and model hashes must match. Length changes use the source aircraft's "
            "m or ft units; angle changes use degrees and thickness ratio is dimensionless. "
            "All unlisted parameters stay fixed; constraints=null inherits source constraints, "
            "whereas [] clears them. Revalidates the complete layout before invoking OpenVSP. "
            "The parent files are preserved. Returns parent lineage, new artifacts, measured "
            "constraint checks, and validation_passed; failed checks do not imply a valid design."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
    )
    def update(request: AircraftRevisionRequest) -> AircraftRevisionResponse:
        return revise_aircraft(request)

    @app.tool(
        name="openvsp.inspect",
        description="Read component IDs and saved OpenVSP parameters without modifying the model or requiring a binary.",
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    def inspect(request: OpenVSPGeometryRequest) -> OpenVSPInspectResponse:
        return describe_geometry(request.geometry_file)

    @app.tool(
        name="openvsp.modify",
        description="Apply trusted raw OpenVSP script commands to an existing model in place. Returns retained script, model snapshot, and logs.",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
        ),
    )
    def modify(request: OpenVSPRequest) -> OpenVSPResponse:
        return execute_openvsp(request.model_copy(update={"run_vspaero": False}))

    @app.tool(
        name="openvsp.run_vspaero",
        description="Apply trusted raw edits, then run the standalone solver for a preconfigured VSPAero case base (case_name). Requires existing solver inputs and mesh.",
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
        ),
    )
    def run_vspaero(request: OpenVSPRequest) -> OpenVSPResponse:
        return execute_openvsp(request.model_copy(update={"run_vspaero": True}))
