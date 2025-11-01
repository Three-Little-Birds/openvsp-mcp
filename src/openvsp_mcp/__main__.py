"""Command-line entry point for openvsp-mcp."""

from __future__ import annotations

import argparse
import json
import sys

from mcp.server.fastmcp import FastMCP

from .tool import build_tool

SERVICE_NAME = "openvsp-mcp"
SERVICE_DESCRIPTION = "OpenVSP/VSPAero automation helpers for MCP agents."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=SERVICE_NAME,
        description="Run the openvsp MCP server (STDIO transport).",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print basic metadata about the MCP service and exit.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="Transport to use (only stdio is supported today).",
    )
    args = parser.parse_args(argv)

    app = FastMCP(SERVICE_NAME, SERVICE_DESCRIPTION)
    build_tool(app)

    if args.describe:
        metadata = {
            "name": SERVICE_NAME,
            "description": SERVICE_DESCRIPTION,
            "default_transport": "stdio",
        }
        print(json.dumps(metadata, indent=2))
        return 0

    if args.transport != "stdio":
        parser.error("only the stdio transport is supported at the moment")

    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
