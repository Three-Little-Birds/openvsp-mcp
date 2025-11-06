"""Utilities for read-only OpenVSP inspection."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .core import OPENVSP_BIN, _OK_EXIT_CODES, _write_script
from .models import OpenVSPInspectResponse, OpenVSPRequest


def describe_geometry(geometry_file: str) -> OpenVSPInspectResponse:
    """Run OpenVSP in describe mode and parse high-level geometry information."""

    with tempfile.TemporaryDirectory(prefix="openvsp_mcp_describe_") as tmpdir:
        temp_request = OpenVSPRequest(
            geometry_file=geometry_file,
            set_commands=[],
            run_vspaero=False,
            case_name="describe",
        )
        script_path = _write_script(temp_request, Path(tmpdir))

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

        tree = ET.parse(geometry_file)
        root = tree.getroot()
        geom_ids: list[str] = []
        wing_names: list[str] = []
        info_lines: list[str] = []

        for geom in root.findall(".//Geom"):
            name_elem = geom.find("ParmContainer/Name")
            geom_name = name_elem.text if name_elem is not None else ""
            id_elem = geom.find("ParmContainer/ID")
            geom_id = id_elem.text if id_elem is not None else ""
            type_elem = geom.find("GeomBase/TypeName")
            geom_type = type_elem.text if type_elem is not None else ""

            if geom_id:
                geom_ids.append(geom_id)
            if geom_type.lower() == "wing" and geom_name:
                wing_names.append(geom_name)
            info_lines.append(f"{geom_id or 'UNKNOWN'}:{geom_name or 'Unnamed'}:{geom_type or 'Unknown'}")

        return OpenVSPInspectResponse(
            geom_ids=geom_ids,
            wing_names=wing_names,
            info_log="\n".join(info_lines),
        )


__all__ = ["describe_geometry"]
