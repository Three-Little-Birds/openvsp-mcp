"""Core subprocess helpers for OpenVSP/VSPAero automation."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .models import OpenVSPRequest, OpenVSPResponse

OPENVSP_BIN = os.environ.get("OPENVSP_BIN", "vsp")
VSPAERO_BIN = os.environ.get("VSPAERO_BIN", "vspaero")


def execute_openvsp(request: OpenVSPRequest) -> OpenVSPResponse:
    """Run OpenVSP (and optionally VSPAero) using the provided request."""

    with tempfile.TemporaryDirectory(prefix="openvsp_mcp_") as tmpdir:
        workdir = Path(tmpdir)
        script_path = _write_script(request, workdir)

        try:
            result = subprocess.run(
                [OPENVSP_BIN, "-script", str(script_path)],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("OpenVSP binary not found") from exc

        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="ignore"))

        vspaero_output: str | None = None
        if request.run_vspaero:
            try:
                aero = subprocess.run(
                    [VSPAERO_BIN, request.geometry_file, request.case_name],
                    check=False,
                    capture_output=True,
                )
            except FileNotFoundError as exc:  # pragma: no cover
                raise RuntimeError("VSPAero binary not found") from exc

            if aero.returncode != 0:
                raise RuntimeError(aero.stderr.decode("utf-8", errors="ignore"))
            vspaero_output = str(Path(request.case_name).with_suffix(".adb"))

        return OpenVSPResponse(script_path=str(script_path), result_path=vspaero_output)


def _write_script(request: OpenVSPRequest, working_dir: Path) -> Path:
    script_path = working_dir / "automation.vspscript"
    lines = ["// Auto-generated", f"vsp_read {request.geometry_file}"]
    lines.extend(cmd.command for cmd in request.set_commands)
    lines.append(f"vsp_write {request.geometry_file}")
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return script_path


__all__ = ["execute_openvsp", "OPENVSP_BIN", "VSPAERO_BIN"]
