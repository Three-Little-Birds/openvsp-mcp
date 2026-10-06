from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from openvsp_mcp.aircraft import create_aircraft
from openvsp_mcp.models import (
    AircraftCreateRequest,
    AircraftCreateResponse,
    AircraftRevisionRequest,
)
from openvsp_mcp.revisions import RevisionSourceError, revise_aircraft

EXAMPLE = Path(__file__).parents[1] / "examples" / "conventional_aircraft.json"
native = pytest.mark.skipif(
    not os.environ.get("OPENVSP_BIN"), reason="Set OPENVSP_BIN to run native integration tests"
)


@pytest.fixture
def creation_request(tmp_path: Path) -> AircraftCreateRequest:
    payload = json.loads(EXAMPLE.read_text())
    payload["output_directory"] = str(tmp_path)
    payload["constraints"] = [{"metric": "wing_span_m", "maximum": 3.5}]
    return AircraftCreateRequest.model_validate(payload)


def _snapshot(directory: str | Path) -> dict[str, bytes]:
    directory = Path(directory)
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _mock_bundle(
    directory: Path, request: AircraftCreateRequest, candidate_id: str
) -> AircraftCreateResponse:
    """Write a managed bundle without invoking or simulating native geometry validation."""
    directory.mkdir()
    geometry_path = directory / f"{request.aircraft.name}.vsp3"
    geometry_path.write_text(request.aircraft.model_dump_json(), encoding="utf-8")
    specification_path = directory / "specification.json"
    specification_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    script_path = directory / "build.vspscript"
    script_path.write_text("// mock builder\n", encoding="utf-8")
    report_path = directory / "report.json"
    response = AircraftCreateResponse(
        candidate_id=candidate_id,
        geometry_sha256=hashlib.sha256(geometry_path.read_bytes()).hexdigest(),
        specification_sha256=hashlib.sha256(specification_path.read_bytes()).hexdigest(),
        geometry_path=str(geometry_path),
        script_path=str(script_path),
        specification_path=str(specification_path),
        report_path=str(report_path),
        artifact_directory=str(directory),
        openvsp_version="mock",
        components=[],
        measurements={},
        validation_passed=False,
        checks=[],
        assumptions=[],
    )
    report_path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
    return response


@pytest.fixture
def managed_parent(tmp_path: Path, creation_request: AircraftCreateRequest):
    payload = creation_request.model_dump()
    payload.update(timeout_seconds=47.0, relative_tolerance=1e-4, absolute_tolerance=1e-7)
    request = AircraftCreateRequest.model_validate(payload)
    return _mock_bundle(tmp_path / "parent", request, "parent-id")


@pytest.mark.parametrize(
    "constraints",
    [None, [], [{"metric": "wing_span_m", "minimum": 3.4, "maximum": 3.6}]],
)
def test_revision_merges_constraints_and_retains_parent_settings(
    managed_parent: AircraftCreateResponse,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constraints,
) -> None:
    from openvsp_mcp import revisions

    original = _snapshot(managed_parent.artifact_directory)
    captured = []

    def build(request: AircraftCreateRequest, *, provenance=None) -> AircraftCreateResponse:
        captured.append(request)
        assert provenance["parent_candidate_id"] == managed_parent.candidate_id
        assert provenance["revision_request"]["constraints"] == constraints
        return _mock_bundle(tmp_path / "child", request, "child-id")

    monkeypatch.setattr(revisions, "create_aircraft", build)
    result = revise_aircraft(
        AircraftRevisionRequest(
            source_report_path=managed_parent.report_path,
            changes=[{"parameter": "wing.span", "value": 3.5}],
            constraints=constraints,
        )
    )
    request = captured[0]
    assert request.aircraft.wing.span == 3.5
    assert request.aircraft.wing.root_chord == 0.65
    assert request.aircraft.units == "m"
    assert request.output_directory == str(tmp_path)
    assert request.timeout_seconds == 47
    assert request.relative_tolerance == 1e-4
    assert request.absolute_tolerance == 1e-7
    expected_constraints = (
        [{"metric": "wing_span_m", "minimum": None, "maximum": 3.5}]
        if constraints is None
        else [
            dict(item, minimum=item.get("minimum"), maximum=item.get("maximum"))
            for item in constraints
        ]
    )
    assert [item.model_dump() for item in request.constraints] == expected_constraints
    assert result.parent_candidate_id == managed_parent.candidate_id
    assert result.parent_geometry_sha256 == managed_parent.geometry_sha256
    assert result.parent_specification_sha256 == managed_parent.specification_sha256
    assert result.candidate_id != managed_parent.candidate_id
    assert result.artifact_directory != managed_parent.artifact_directory
    assert result.changes[0].model_dump() == {
        "parameter": "wing.span",
        "before": 4.0,
        "after": 3.5,
        "units": "m",
    }
    assert json.loads(Path(result.revision_request_path).read_text())["changes"] == [
        {"parameter": "wing.span", "value": 3.5}
    ]
    assert json.loads(Path(result.report_path).read_text())["parent_candidate_id"] == "parent-id"
    assert _snapshot(managed_parent.artifact_directory) == original


@pytest.mark.parametrize("artifact", ["specification_path", "geometry_path"])
def test_modified_parent_is_rejected_before_build(
    managed_parent: AircraftCreateResponse, monkeypatch: pytest.MonkeyPatch, artifact: str
) -> None:
    from openvsp_mcp import revisions

    path = Path(getattr(managed_parent, artifact))
    path.write_bytes(path.read_bytes() + b"\n")
    original = _snapshot(managed_parent.artifact_directory)

    def unexpected_build(request):
        pytest.fail("A modified source must be rejected before native build")

    monkeypatch.setattr(revisions, "create_aircraft", unexpected_build)
    with pytest.raises(RevisionSourceError, match="hash mismatch"):
        revise_aircraft(
            AircraftRevisionRequest(
                source_report_path=managed_parent.report_path,
                changes=[{"parameter": "wing.span", "value": 3.5}],
            )
        )
    assert _snapshot(managed_parent.artifact_directory) == original


@pytest.mark.parametrize(
    "change",
    [
        {"parameter": "fuselage.length", "value": 2.0},
        {"parameter": "vertical_tail.dihedral_deg", "value": 5.0},
        {"parameter": "wing.span", "value": -1.0},
    ],
)
def test_invalid_merged_aircraft_is_rejected_before_build(
    managed_parent: AircraftCreateResponse, monkeypatch: pytest.MonkeyPatch, change
) -> None:
    from openvsp_mcp import revisions

    original = _snapshot(managed_parent.artifact_directory)

    def unexpected_build(request):
        pytest.fail("An invalid merged layout must be rejected before native build")

    monkeypatch.setattr(revisions, "create_aircraft", unexpected_build)
    with pytest.raises(ValidationError):
        revise_aircraft(
            AircraftRevisionRequest(source_report_path=managed_parent.report_path, changes=[change])
        )
    assert _snapshot(managed_parent.artifact_directory) == original


def test_revision_rejects_duplicate_changes_and_untyped_paths() -> None:
    with pytest.raises(ValidationError, match="only once"):
        AircraftRevisionRequest(
            source_report_path="report.json",
            changes=[
                {"parameter": "wing.span", "value": 3.5},
                {"parameter": "wing.span", "value": 3.6},
            ],
        )
    for parameter in ("units", "name", "wing.unknown", "wing.command"):
        with pytest.raises(ValidationError):
            AircraftRevisionRequest(
                source_report_path="report.json", changes=[{"parameter": parameter, "value": 1.0}]
            )


def test_failed_revision_retains_provenance_before_native_execution(
    managed_parent: AircraftCreateResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openvsp_mcp import aircraft

    original = _snapshot(managed_parent.artifact_directory)
    failed_directories = []

    def fail_native(script_path, geometry_path, timeout_seconds):
        directory = Path(script_path).parent
        failed_directories.append(directory)
        provenance = json.loads((directory / "provenance.json").read_text())
        assert provenance["operation"] == "revision"
        assert provenance["parent_candidate_id"] == managed_parent.candidate_id
        assert provenance["parent_report_path"] == managed_parent.report_path
        assert provenance["parent_geometry_sha256"] == managed_parent.geometry_sha256
        assert provenance["parent_specification_sha256"] == managed_parent.specification_sha256
        assert provenance["revision_request"]["changes"] == [
            {"parameter": "wing.span", "value": 3.5}
        ]
        assert provenance["changes"] == [
            {"parameter": "wing.span", "before": 4.0, "after": 3.5, "units": "m"}
        ]
        specification = json.loads((directory / "specification.json").read_text())
        assert specification["aircraft"]["wing"]["span"] == 3.5
        assert specification["constraints"] == [
            {"metric": "wing_span_m", "minimum": None, "maximum": 3.5}
        ]
        assert timeout_seconds == 47
        raise RuntimeError("Simulated native process failure")

    monkeypatch.setattr(aircraft, "run_openvsp", fail_native)
    with pytest.raises(RuntimeError, match="native process failure"):
        revise_aircraft(
            AircraftRevisionRequest(
                source_report_path=managed_parent.report_path,
                changes=[{"parameter": "wing.span", "value": 3.5}],
            )
        )
    assert len(failed_directories) == 1
    failed_directory = failed_directories[0]
    assert failed_directory != Path(managed_parent.artifact_directory)
    assert (failed_directory / "provenance.json").is_file()
    assert (failed_directory / "specification.json").is_file()
    assert (failed_directory / "build.vspscript").is_file()
    assert not (failed_directory / "report.json").exists()
    assert _snapshot(managed_parent.artifact_directory) == original


@native
def test_native_revision_repairs_failed_span_and_preserves_lineage(
    creation_request: AircraftCreateRequest,
) -> None:
    parent = create_aircraft(creation_request)
    assert not parent.validation_passed
    original = _snapshot(parent.artifact_directory)
    child = revise_aircraft(
        AircraftRevisionRequest(
            source_report_path=parent.report_path,
            changes=[{"parameter": "wing.span", "value": 3.5}],
        )
    )
    assert child.validation_passed, [item for item in child.checks if not item.passed]
    assert child.measurements["wing_span_m"] == pytest.approx(3.5)
    assert child.parent_candidate_id == parent.candidate_id
    assert child.parent_geometry_sha256 == parent.geometry_sha256
    assert child.parent_specification_sha256 == parent.specification_sha256
    provenance = json.loads((Path(child.artifact_directory) / "provenance.json").read_text())
    assert provenance["parent_candidate_id"] == parent.candidate_id
    assert child.candidate_id != parent.candidate_id
    assert child.geometry_sha256 != parent.geometry_sha256
    assert Path(child.geometry_path).parent != Path(parent.geometry_path).parent
    assert _snapshot(parent.artifact_directory) == original
    grandchild = revise_aircraft(
        AircraftRevisionRequest(
            source_report_path=child.report_path,
            changes=[{"parameter": "wing.sweep_deg", "value": 10.0}],
        )
    )
    assert grandchild.validation_passed
    assert grandchild.parent_candidate_id == child.candidate_id
    assert grandchild.measurements["wing_sweep_deg"] == pytest.approx(10)
    assert grandchild.changes[0].units == "deg"


@native
@pytest.mark.parametrize(
    ("constraints", "passed"),
    [(None, False), ([], True), ([{"metric": "wing_span_m", "minimum": 3.7}], True)],
)
def test_native_revision_constraint_policy(
    creation_request: AircraftCreateRequest, constraints, passed: bool
) -> None:
    parent = create_aircraft(creation_request)
    child = revise_aircraft(
        AircraftRevisionRequest(
            source_report_path=parent.report_path,
            changes=[{"parameter": "wing.span", "value": 3.8}],
            constraints=constraints,
        )
    )
    assert child.validation_passed is passed
    assert Path(child.geometry_path).is_file()


@native
def test_native_revision_lengths_use_parent_feet_units(
    creation_request: AircraftCreateRequest,
) -> None:
    payload = creation_request.model_dump()
    payload["aircraft"]["units"] = "ft"
    for name in ("fuselage", "wing", "horizontal_tail", "vertical_tail"):
        for field in ("length", "width", "height", "span", "root_chord", "tip_chord", "x_le", "z"):
            if field in payload["aircraft"][name]:
                payload["aircraft"][name][field] /= 0.3048
    parent = create_aircraft(AircraftCreateRequest.model_validate(payload))
    child = revise_aircraft(
        AircraftRevisionRequest(
            source_report_path=parent.report_path,
            changes=[{"parameter": "wing.span", "value": 3.5 / 0.3048}],
        )
    )
    assert child.validation_passed
    assert child.measurements["wing_span_m"] == pytest.approx(3.5)
    assert child.changes[0].units == "ft"
    assert child.changes[0].before == pytest.approx(4 / 0.3048)
    saved = json.loads(Path(child.specification_path).read_text())
    assert saved["aircraft"]["units"] == "ft"
    assert saved["constraints"] == [{"metric": "wing_span_m", "minimum": None, "maximum": 3.5}]


@native
def test_native_revision_relocated_bundle(
    creation_request: AircraftCreateRequest, tmp_path: Path
) -> None:
    parent = create_aircraft(creation_request)
    moved = tmp_path / "relocated" / "parent"
    moved.parent.mkdir()
    shutil.move(parent.artifact_directory, moved)
    original = _snapshot(moved)
    assert not Path(parent.report_path).exists()
    child = revise_aircraft(
        AircraftRevisionRequest(
            source_report_path=str(moved / "report.json"),
            changes=[{"parameter": "wing.span", "value": 3.5}],
        )
    )
    assert child.validation_passed
    assert Path(child.artifact_directory).parent == moved.parent
    assert child.parent_report_path == str(moved / "report.json")
    assert _snapshot(moved) == original


@native
def test_failed_native_revision_keeps_parent_bundle(
    creation_request: AircraftCreateRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openvsp_mcp import aircraft

    parent = create_aircraft(creation_request)
    original = _snapshot(parent.artifact_directory)

    def fail_native(*args, **kwargs):
        raise RuntimeError("Simulated native process failure")

    monkeypatch.setattr(aircraft, "run_openvsp", fail_native)
    with pytest.raises(RuntimeError, match="native process failure"):
        revise_aircraft(
            AircraftRevisionRequest(
                source_report_path=parent.report_path,
                changes=[{"parameter": "wing.span", "value": 3.5}],
            )
        )
    assert _snapshot(parent.artifact_directory) == original
