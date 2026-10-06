from __future__ import annotations

import shutil
import subprocess
from importlib import resources
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from openvsp_mcp.core import COMPLETION_MARKER, ERROR_MARKER, execute_openvsp, script_string
from openvsp_mcp.describe import describe_geometry
from openvsp_mcp.fastapi_app import create_app
from openvsp_mcp.models import OpenVSPRequest, VSPCommand


@pytest.fixture
def geometry(tmp_path: Path) -> Path:
    path = tmp_path / "input.vsp3"
    with resources.as_file(resources.files("openvsp_mcp.data") / "rect_wing.vsp3") as source:
        shutil.copyfile(source, path)
    return path


def _fake_success(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    workdir = kwargs["cwd"]
    shutil.copyfile(resources.files("openvsp_mcp.data") / "rect_wing.vsp3", workdir / "model.vsp3")
    return subprocess.CompletedProcess(args, 0, f" {COMPLETION_MARKER}\n", "")


def test_execute_retains_artifacts(geometry: Path, tmp_path: Path) -> None:
    request = OpenVSPRequest(
        geometry_file=str(geometry),
        set_commands=[VSPCommand(command="Update()")],
        run_vspaero=False,
        output_directory=str(tmp_path / "artifacts"),
    )
    with mock.patch("openvsp_mcp.core.subprocess.run", side_effect=_fake_success):
        response = execute_openvsp(request)
    assert Path(response.script_path).is_file()
    assert Path(response.geometry_path).is_file()
    assert (Path(response.artifact_directory) / "openvsp.stdout.log").is_file()
    assert (Path(response.artifact_directory) / "request.json").is_file()
    assert response.result_path is None


@pytest.mark.parametrize(
    "stdout", ["compile error", f"{ERROR_MARKER}missing parameter\n{COMPLETION_MARKER}"]
)
def test_failed_native_run_preserves_input(geometry: Path, tmp_path: Path, stdout: str) -> None:
    before = geometry.read_bytes()
    request = OpenVSPRequest(
        geometry_file=str(geometry), run_vspaero=False, output_directory=str(tmp_path)
    )
    with (
        mock.patch(
            "openvsp_mcp.core.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout, ""),
        ),
        pytest.raises(RuntimeError, match="did not complete"),
    ):
        execute_openvsp(request)
    assert geometry.read_bytes() == before


def test_timeout_retains_log(geometry: Path, tmp_path: Path) -> None:
    request = OpenVSPRequest(
        geometry_file=str(geometry),
        run_vspaero=False,
        output_directory=str(tmp_path),
        timeout_seconds=1,
    )
    with (
        mock.patch(
            "openvsp_mcp.core.subprocess.run",
            side_effect=subprocess.TimeoutExpired("vsp", 1, output=b"partial"),
        ),
        pytest.raises(RuntimeError, match="exceeded 1 seconds"),
    ):
        execute_openvsp(request)
    assert next(tmp_path.glob("run_*/openvsp.stdout.log")).read_text() == "partial"


def test_inspect_is_read_only_and_excludes_nested_metadata(geometry: Path) -> None:
    before = geometry.read_bytes()
    with mock.patch(
        "subprocess.run", side_effect=AssertionError("Inspection must not execute a binary")
    ):
        response = describe_geometry(str(geometry))
    assert geometry.read_bytes() == before
    assert response.wing_names == ["RectWing"]
    assert len(response.components) == 1
    assert response.components[0].parameters["WingGeom"]["TotalSpan"] == 18


def test_invalid_model_has_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.vsp3"
    path.write_text("<unrelated/>")
    with pytest.raises(RuntimeError, match="Not an OpenVSP"):
        describe_geometry(str(path))


def test_script_quotes_paths() -> None:
    assert script_string('C:\\Aircraft\\a"b.vsp3') == '"C:\\\\Aircraft\\\\a\\"b.vsp3"'


def test_fastapi_modify_and_inspect(geometry: Path, tmp_path: Path) -> None:
    client = TestClient(create_app())
    payload = {
        "geometry_file": str(geometry),
        "output_directory": str(tmp_path),
        "set_commands": [],
    }
    with mock.patch("openvsp_mcp.core.subprocess.run", side_effect=_fake_success):
        response = client.post("/vsp/modify", json=payload)
    assert response.status_code == 200
    assert Path(response.json()["script_path"]).is_file()
    assert client.post("/vsp/inspect", json={"geometry_file": str(geometry)}).status_code == 200
    assert client.post("/vsp/aircraft", json={"aircraft": {}}).status_code == 422


def test_vspaero_uses_case_base_and_requires_output(geometry: Path, tmp_path: Path) -> None:
    case = tmp_path / "solver.case"
    Path(f"{case}.vspaero").write_text("configured solver inputs")
    request = OpenVSPRequest(
        geometry_file=str(geometry), case_name=str(case), output_directory=str(tmp_path)
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return _fake_success(args, **kwargs)
        Path(f"{case}.adb").write_bytes(b"new ADB")
        return subprocess.CompletedProcess(args, 0, "", "")

    with mock.patch("openvsp_mcp.core.subprocess.run", side_effect=fake_run):
        response = execute_openvsp(request)
    assert calls[1][1:] == [str(case)]
    assert response.result_path == str(Path(f"{case}.adb"))


def test_vspaero_rejects_stale_adb(geometry: Path, tmp_path: Path) -> None:
    case = tmp_path / "case"
    Path(f"{case}.vspaero").write_text("configured solver inputs")
    Path(f"{case}.adb").write_bytes(b"previous result")
    request = OpenVSPRequest(
        geometry_file=str(geometry), case_name=str(case), output_directory=str(tmp_path)
    )
    with (
        mock.patch("openvsp_mcp.core.subprocess.run", side_effect=_fake_success),
        pytest.raises(RuntimeError, match="produced no ADB"),
    ):
        execute_openvsp(request)
