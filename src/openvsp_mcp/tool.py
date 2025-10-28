"""python-sdk MCP integration helper."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .core import execute_openvsp
from .models import OpenVSPRequest, OpenVSPResponse


def build_tool(app: FastMCP) -> None:
    """Register the OpenVSP tool on the given MCP app."""

    @app.tool()
    def vsp(request: OpenVSPRequest) -> OpenVSPResponse:  # type: ignore[valid-type]
        return execute_openvsp(request)


__all__ = ["build_tool"]
