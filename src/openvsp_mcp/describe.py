"""Utilities for read-only OpenVSP inspection."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .core import OPENVSP_BIN, _OK_EXIT_CODES
from .models import OpenVSPInspectResponse


def describe_geometry(geometry_file: str) -> OpenVSPInspectResponse:
    """Run OpenVSP in describe mode and parse high-level geometry information."""

    with tempfile.TemporaryDirectory(prefix="openvsp_mcp_describe_") as tmpdir:
        script_path = Path(tmpdir) / "describe.vspscript"
        script_path.write_text(
            "\n".join(
                [
                    "// Auto-generated describe script",
                    "void main() {",
                    "    ClearVSPModel();",
                    f"    ReadVSPFile(\"{geometry_file}\");",
                    "    Print(\"__MCP_BEGIN__\");",
                    "    ScriptDeskDescribe();",
                    "    Print(\"__MCP_END__\");",
                    "}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [OPENVSP_BIN, "-script", str(script_path)],
            check=False,
            capture_output=True,
        )
        if result.returncode not in _OK_EXIT_CODES:
            message = result.stderr.decode("utf-8", errors="ignore").strip()
            if not message:
                message = result.stdout.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(message or "OpenVSP describe run failed")

        stdout = result.stdout.decode("utf-8", errors="ignore")
        info = stdout.split("__MCP_BEGIN__", 1)[-1].split("__MCP_END__", 1)[0]

        geom_ids: list[str] = []
        wing_names: list[str] = []
        for line in info.splitlines():
            line = line.strip()
            if line.startswith("Geom ID:"):
                geom_ids.append(line.split(":", 1)[-1].strip())
            if line.startswith("Wing:"):
                wing_names.append(line.split(":", 1)[-1].strip())

        return OpenVSPInspectResponse(
            geom_ids=geom_ids,
            wing_names=wing_names,
            info_log=info.strip(),
        )


__all__ = ["describe_geometry"]
