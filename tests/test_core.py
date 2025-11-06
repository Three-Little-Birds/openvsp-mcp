from __future__ import annotations

import shutil
import subprocess
from http import HTTPStatus
from pathlib import Path
from unittest import mock

from importlib import resources

from fastapi.testclient import TestClient

from openvsp_mcp.core import execute_openvsp
from openvsp_mcp.describe import describe_geometry
from openvsp_mcp.fastapi_app import create_app
from openvsp_mcp.models import (
    OpenVSPGeometryRequest,
    OpenVSPRequest,
    VSPCommand,
)


def _fake_run(
    args: list[str],
    *,
    check: bool,
    capture_output: bool,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args, 0, b"ok", b"")


def _fake_describe_run(
    args: list[str],
    *,
    check: bool,
    capture_output: bool,
) -> subprocess.CompletedProcess[bytes]:
    stdout = b""
    return subprocess.CompletedProcess(args, 0, stdout, b"")


def test_execute_openvsp(tmp_path: Path) -> None:
    """Demonstrate how a geometry edit request is translated into CLI calls."""
    request = OpenVSPRequest(
        geometry_file="models/demo.vsp3",
        set_commands=[VSPCommand(command="vsp_set wing Span 0.5")],
        run_vspaero=True,
        case_name="hover",
    )

    with mock.patch("openvsp_mcp.core.subprocess.run", side_effect=_fake_run):
        response = execute_openvsp(request)

    assert response.result_path == "hover.adb"
    assert response.script_path.endswith("automation.vspscript")


def test_fastapi_endpoint(tmp_path: Path) -> None:
    """Exercise the HTTP layer so agents can copy a working JSON request."""
    app = create_app()
    client = TestClient(app)
    payload = {
        "geometry_file": "models/demo.vsp3",
        "set_commands": [{"command": "vsp_set wing Span 0.5"}],
        "case_name": "hover",
    }

    with mock.patch("openvsp_mcp.core.subprocess.run", side_effect=_fake_run):
        response = client.post("/vsp/modify", json=payload)
        run_response = client.post("/vsp/run", json=payload | {"run_vspaero": True})

    assert response.status_code == HTTPStatus.OK
    assert run_response.status_code == HTTPStatus.OK
    assert run_response.json()["result_path"] == "hover.adb"


def test_describe_geometry(tmp_path: Path) -> None:
    with resources.as_file(resources.files("openvsp_mcp.data") / "rect_wing.vsp3") as src:
        geom_path = tmp_path / "rect.vsp3"
        shutil.copy(src, geom_path)
    request = OpenVSPGeometryRequest(geometry_file=str(geom_path))

    with mock.patch("openvsp_mcp.describe.subprocess.run", side_effect=_fake_describe_run):
        response = describe_geometry(request.geometry_file)

    assert "RectWing" in response.wing_names
