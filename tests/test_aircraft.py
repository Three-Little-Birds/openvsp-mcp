from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from openvsp_mcp import (
    AircraftCreateRequest,
    OpenVSPRequest,
    VSPCommand,
    create_aircraft,
    execute_openvsp,
)
from openvsp_mcp.aircraft import expected_measurements, validate_measurements
from openvsp_mcp.describe import describe_geometry

EXAMPLE = Path(__file__).parents[1] / "examples" / "conventional_aircraft.json"


@pytest.fixture
def aircraft_request(tmp_path: Path) -> AircraftCreateRequest:
    payload = json.loads(EXAMPLE.read_text())
    payload["output_directory"] = str(tmp_path)
    return AircraftCreateRequest.model_validate(payload)


@pytest.mark.parametrize("invalid", [-1, 0, float("nan"), float("inf"), True, "4"])
def test_rejects_invalid_dimensions(aircraft_request: AircraftCreateRequest, invalid) -> None:
    payload = aircraft_request.model_dump()
    payload["aircraft"]["wing"]["span"] = invalid
    with pytest.raises(ValidationError):
        AircraftCreateRequest.model_validate(payload)


def test_rejects_unknown_fields_and_inverted_constraints(
    aircraft_request: AircraftCreateRequest,
) -> None:
    payload = aircraft_request.model_dump()
    payload["aircraft"]["wing"]["sweep"] = 20
    with pytest.raises(ValidationError, match="Extra inputs"):
        AircraftCreateRequest.model_validate(payload)
    payload = aircraft_request.model_dump()
    payload["constraints"] = [{"metric": "wing_span_m", "minimum": 5, "maximum": 4}]
    with pytest.raises(ValidationError, match="minimum must not exceed"):
        AircraftCreateRequest.model_validate(payload)


def test_rejects_tilted_fin(aircraft_request: AircraftCreateRequest) -> None:
    payload = aircraft_request.model_dump()
    payload["aircraft"]["vertical_tail"]["dihedral_deg"] = 10
    with pytest.raises(ValidationError, match="upright fin"):
        AircraftCreateRequest.model_validate(payload)


def test_units_and_projected_aspect_ratio(aircraft_request: AircraftCreateRequest) -> None:
    aircraft_request.aircraft.units = "ft"
    expected = expected_measurements(aircraft_request.aircraft)
    assert expected["wing_span_m"] == pytest.approx(4 * 0.3048)
    assert expected["wing_area_m2"] == pytest.approx(1.94 * 0.3048**2)
    assert expected["wing_aspect_ratio"] == pytest.approx(
        (4 * math.cos(math.radians(4))) ** 2 / 1.94
    )


def test_constraint_failure_is_reported(aircraft_request: AircraftCreateRequest) -> None:
    actual = expected_measurements(aircraft_request.aircraft)
    actual.update({"aircraft_x_extent_m": 3.2})
    checks = validate_measurements(aircraft_request, actual)
    assert any(not check.passed and check.metric == "aircraft_x_extent_m" for check in checks)
    actual["wing_root_chord_m"] += 0.1
    assert any(
        not check.passed and check.metric == "wing_root_chord_m"
        for check in validate_measurements(aircraft_request, actual)
    )


native = pytest.mark.skipif(
    not os.environ.get("OPENVSP_BIN"), reason="Set OPENVSP_BIN to run native integration tests"
)


@native
@pytest.mark.parametrize("units", ["m", "ft"])
def test_native_build_and_saved_dimensions(
    aircraft_request: AircraftCreateRequest, units: str
) -> None:
    aircraft_request.aircraft.units = units
    if units == "ft":
        for part in (
            aircraft_request.aircraft.fuselage,
            aircraft_request.aircraft.wing,
            aircraft_request.aircraft.horizontal_tail,
            aircraft_request.aircraft.vertical_tail,
        ):
            for field in (
                "length",
                "width",
                "height",
                "span",
                "root_chord",
                "tip_chord",
                "x_le",
                "z",
            ):
                if hasattr(part, field):
                    setattr(part, field, getattr(part, field) / 0.3048)
    response = create_aircraft(aircraft_request)
    assert response.validation_passed, [
        check.model_dump() for check in response.checks if not check.passed
    ]
    assert response.measurements["wing_span_m"] == pytest.approx(4)
    assert response.measurements["wing_area_m2"] == pytest.approx(1.94)
    assert response.measurements["vertical_tail_span_m"] == pytest.approx(0.65)
    assert len(response.components) == 4
    for field in ("geometry_path", "script_path", "specification_path", "report_path"):
        assert Path(getattr(response, field)).is_file()
    assert json.loads(Path(response.report_path).read_text())["validation_passed"]


@native
def test_native_unsatisfied_constraint_keeps_reviewable_model(
    aircraft_request: AircraftCreateRequest,
) -> None:
    payload = aircraft_request.model_dump()
    payload["constraints"] = [{"metric": "wing_span_m", "maximum": 3.5}]
    response = create_aircraft(AircraftCreateRequest.model_validate(payload))
    assert not response.validation_passed
    assert response.checks[-1].actual == pytest.approx(4)
    assert Path(response.geometry_path).is_file()


@native
def test_native_edit_and_api_error_preserve_model(
    aircraft_request: AircraftCreateRequest, tmp_path: Path
) -> None:
    response = create_aircraft(aircraft_request)
    source = tmp_path / 'aircraft with "quote".vsp3'
    shutil.copyfile(response.geometry_path, source)
    edit = OpenVSPRequest(
        geometry_file=str(source),
        output_directory=str(tmp_path),
        run_vspaero=False,
        set_commands=[
            VSPCommand(command='string wing = FindGeom("Wing", 0)'),
            VSPCommand(command='SetParmVal(wing, "TotalSpan", "WingGeom", 4.2)'),
        ],
    )
    edited = execute_openvsp(edit)
    assert Path(edited.script_path).exists()
    wing = next(
        component
        for component in describe_geometry(str(source)).components
        if component.name == "Wing"
    )
    assert wing.parameters["WingGeom"]["TotalSpan"] == pytest.approx(4.2)
    before = source.read_bytes()
    edit.set_commands = [VSPCommand(command='SetParmVal("invalid", "missing", "missing", 5)')]
    with pytest.raises(RuntimeError, match="API_ERROR"):
        execute_openvsp(edit)
    assert source.read_bytes() == before


@native
def test_native_exact_area_bound_allows_roundoff(aircraft_request: AircraftCreateRequest) -> None:
    payload = aircraft_request.model_dump()
    payload["constraints"] = [{"metric": "wing_area_m2", "maximum": 1.94}]
    response = create_aircraft(AircraftCreateRequest.model_validate(payload))
    assert response.validation_passed
    assert response.measurements["wing_area_m2"] == pytest.approx(1.94)
