"""Command-line entry point for openvsp-mcp."""

from __future__ import annotations

import argparse
import json
import os
import sys

from mcp.server.fastmcp import FastMCP

from .tool import build_tool

SERVICE_NAME = "openvsp-mcp"
SERVICE_DESCRIPTION = "OpenVSP/VSPAero automation helpers for MCP agents."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=SERVICE_NAME,
        description="Run the openvsp MCP server.",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print basic metadata about the MCP service and exit.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport to use (stdio, sse, or streamable-http).",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host interface to bind when using SSE or streamable HTTP transports (default 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind when using SSE or streamable HTTP transports (default 8000).",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Mount/path for SSE or streamable HTTP transports (default /mcp).",
    )
    args = parser.parse_args(argv)

    if args.describe:
        metadata = {
            "name": SERVICE_NAME,
            "description": SERVICE_DESCRIPTION,
            "default_transport": "stdio",
        }
        print(json.dumps(metadata, indent=2))
        return 0

    transport = args.transport

    # Resolve host/port/path preferences before instantiating FastMCP so settings can
    # reflect the requested values regardless of environment defaults.
    host_env = os.environ.get("FASTMCP_HOST")
    port_env = os.environ.get("FASTMCP_PORT")
    path_env = os.environ.get("FASTMCP_STREAMABLE_HTTP_PATH")

    host = args.host or host_env or "0.0.0.0"
    port = args.port or (int(port_env) if port_env else 8000)
    mount_path = args.path or path_env or "/mcp"

    app = FastMCP(SERVICE_NAME, SERVICE_DESCRIPTION)
    build_tool(app)

    if transport == "stdio":
        return app.run()

    # Mutate FastMCP settings directly so the server honours requested binding.
    app.settings.host = host
    app.settings.port = port

    if transport == "streamable-http":
        app.settings.streamable_http_path = mount_path
        print(
            f"openvsp-mcp starting (transport=streamable-http) on {app.settings.host}:{app.settings.port}{mount_path}",
            file=sys.stderr,
            flush=True,
        )
        return app.run(transport="streamable-http")

    # SSE transport accepts a mount path parameter during run() invocation.
    print(
        f"openvsp-mcp starting (transport=sse) on {app.settings.host}:{app.settings.port}{mount_path}",
        file=sys.stderr,
        flush=True,
    )
    return app.run(transport="sse", mount_path=mount_path)


if __name__ == "__main__":
    sys.exit(main())
