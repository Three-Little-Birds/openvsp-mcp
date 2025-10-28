from __future__ import annotations

import subprocess
from http import HTTPStatus
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from openvsp_mcp.core import execute_openvsp
from openvsp_mcp.fastapi_app import create_app
from openvsp_mcp.models import OpenVSPRequest, VSPCommand


def _fake_run(
    args: list[str],
    *,
    check: bool,
    capture_output: bool,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args, 0, b"ok", b"")


def test_execute_openvsp(tmp_path: Path) -> None:
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
    app = create_app()
    client = TestClient(app)
    payload = {
        "geometry_file": "models/demo.vsp3",
        "set_commands": [{"command": "vsp_set wing Span 0.5"}],
        "run_vspaero": True,
        "case_name": "hover",
    }

    with mock.patch("openvsp_mcp.core.subprocess.run", side_effect=_fake_run):
        response = client.post("/vsp", json=payload)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["result_path"] == "hover.adb"
