"""Example python-sdk tool for openvsp-mcp."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from openvsp_mcp.tool import build_tool

app = FastMCP("openvsp-mcp", "OpenVSP automation")
build_tool(app)


if __name__ == "__main__":
    # Example usage: echo a request into STDIN when running `uv run mcp dev ...`
    app.run()
