"""python-sdk MCP integration helper."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .core import execute_openvsp
from .describe import describe_geometry
from .models import (
    OpenVSPGeometryRequest,
    OpenVSPInspectResponse,
    OpenVSPRequest,
    OpenVSPResponse,
)


def build_tool(app: FastMCP) -> None:
    """Register OpenVSP automation tooling on an MCP server."""

    @app.tool(
        name="openvsp.inspect",
        description=(
            "Describe an OpenVSP geometry without modifying it. Returns component IDs and raw info."),
        meta={"version": "0.1.0", "categories": ["geometry", "aero", "inspection"]},
    )
    def inspect(request: OpenVSPGeometryRequest) -> OpenVSPInspectResponse:
        return describe_geometry(request.geometry_file)

    @app.tool(
        name="openvsp.modify",
        description=(
            "Apply scripted parameter edits to an OpenVSP model without running VSPAero. "
            "Use set_commands to adjust geometry; returns the generated script path."),
        meta={"version": "0.1.0", "categories": ["geometry"]},
    )
    def modify(request: OpenVSPRequest) -> OpenVSPResponse:
        return execute_openvsp(request.model_copy(update={"run_vspaero": False}))

    @app.tool(
        name="openvsp.run_vspaero",
        description=(
            "Run OpenVSP edits followed by VSPAero. Provide geometry commands and case_name."),
        meta={"version": "0.1.0", "categories": ["geometry", "aero"]},
    )
    def run_vspaero(request: OpenVSPRequest) -> OpenVSPResponse:
        return execute_openvsp(request.model_copy(update={"run_vspaero": True}))


__all__ = ["build_tool"]
