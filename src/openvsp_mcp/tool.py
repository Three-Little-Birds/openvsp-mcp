"""python-sdk MCP integration helper."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .core import execute_openvsp
from .models import OpenVSPRequest, OpenVSPResponse


def build_tool(app: FastMCP) -> None:
    """Register OpenVSP automation tooling on an MCP server."""

    @app.tool(
        name="openvsp.run_vsp",
        description=(
            "Run OpenVSP/VSPAero scripts. Provide geometry operations and analyses to execute. "
            "Returns output archive paths and solver metadata. "
            "Example: {\"script\": \"load wing.vsp3; analysis set vspaero\"}"
        ),
        meta={"version": "0.1.0", "categories": ["geometry", "aero"]},
    )
    def vsp(request: OpenVSPRequest) -> OpenVSPResponse:
        return execute_openvsp(request)


__all__ = ["build_tool"]
