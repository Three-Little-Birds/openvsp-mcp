"""Command-line entry point for openvsp-mcp."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .tool import build_tool

SERVICE_NAME = "openvsp-mcp"
SERVICE_DESCRIPTION = "OpenVSP/VSPAero automation helpers for MCP agents."
SERVICE_INSTRUCTIONS = (
    "Use openvsp_plan_aircraft to size a complete conventional-aircraft baseline, declaring "
    "only user-permitted adjustable dimensions and their bounds. Unlisted dimensions stay fixed. "
    "A ready plan is analytical; pass its create_request to openvsp_create_aircraft for native "
    "validation. Use openvsp_update_aircraft for typed changes to a managed report, retaining "
    "the parent. Pass plan.create_request.constraints when applying a sizing plan as a revision. "
    "Use explicit input units and SI targets/constraint bounds. Inspect validation_passed and checks "
    "before reporting success; do not relax a user's constraints silently. "
    "Existing raw-script tools are for trusted expert use. Generated paths are on the server."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_NAME, description="Run the OpenVSP MCP server.")
    parser.add_argument(
        "--describe", action="store_true", help="Print service metadata and tool schemas."
    )
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--host", help="HTTP bind interface (default 127.0.0.1).")
    parser.add_argument("--port", type=int, help="HTTP port (default 8000).")
    parser.add_argument("--path", help="HTTP mount/path (default /mcp).")
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Additional accepted HTTP Host header, e.g. vsp.example.com; repeat as needed.",
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help="Additional accepted browser Origin, e.g. https://vsp.example.com; repeat as needed.",
    )
    args = parser.parse_args(argv)

    host = args.host or os.environ.get("FASTMCP_HOST", "127.0.0.1")
    try:
        port = args.port if args.port is not None else int(os.environ.get("FASTMCP_PORT", "8000"))
    except ValueError:
        parser.error("FASTMCP_PORT must be an integer")
    if not 1 <= port <= 65535:
        parser.error("port must be between 1 and 65535")
    mount_path = args.path or os.environ.get("FASTMCP_STREAMABLE_HTTP_PATH", "/mcp")
    if not mount_path.startswith("/"):
        parser.error("path must start with /")

    security = TransportSecuritySettings(
        allowed_hosts=[
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            "[::1]",
            "[::1]:*",
            *args.allowed_host,
        ],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            *args.allowed_origin,
        ],
    )
    app = FastMCP(
        SERVICE_NAME,
        instructions=SERVICE_INSTRUCTIONS,
        host=host,
        port=port,
        streamable_http_path=mount_path,
        transport_security=security,
    )
    build_tool(app)
    if args.describe:
        metadata = {
            "name": SERVICE_NAME,
            "description": SERVICE_DESCRIPTION,
            "default_transport": "stdio",
            "tools": [
                tool.model_dump(mode="json", exclude_none=True)
                for tool in asyncio.run(app.list_tools())
            ],
        }
        print(json.dumps(metadata, indent=2))
        return 0
    if args.transport == "stdio":
        app.run()
    else:
        print(
            f"{SERVICE_NAME} starting (transport={args.transport}) on {host}:{port}{mount_path}",
            file=sys.stderr,
            flush=True,
        )
        if args.transport == "streamable-http":
            app.run(transport="streamable-http")
        else:
            app.run(transport="sse", mount_path=mount_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
