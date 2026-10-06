from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from openvsp_mcp import planning
from openvsp_mcp.models import AircraftPlanRequest, AircraftSpec
from openvsp_mcp.planning import plan_aircraft

EXAMPLE = Path(__file__).parents[1] / "examples" / "conventional_aircraft.json"


@pytest.fixture
def aircraft() -> AircraftSpec:
    return AircraftSpec.model_validate(json.loads(EXAMPLE.read_text())["aircraft"])


def _variables(*parameters: str) -> list[dict[str, str | float]]:
    return [
        {"parameter": f"wing.{parameter}", "minimum": 0.1, "maximum": 10.0}
        for parameter in parameters
    ]


def _assert_ready(result) -> None:
    assert result.status == "ready", result.diagnostics
    assert result.aircraft is not None
    assert result.create_request is not None
    assert not any(check.status == "violated" for check in result.checks)


def test_plan_preserves_complete_baseline_and_requires_no_native_binary(
    aircraft: AircraftSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENVSP_BIN", "/does/not/exist")
    result = plan_aircraft(AircraftPlanRequest(aircraft=aircraft))
    _assert_ready(result)
    assert result.aircraft == aircraft
    assert result.changes == []
    assert result.measurements["wing_area_m2"] == pytest.approx(1.94)


def test_area_and_taper_size_chords_with_fixed_span(aircraft: AircraftSpec) -> None:
    request = AircraftPlanRequest(
        aircraft=aircraft,
        adjustable=_variables("root_chord", "tip_chord"),
        targets={"area_m2": 2.0, "taper_ratio": 0.5},
    )
    result = plan_aircraft(request)
    _assert_ready(result)
    assert result.aircraft.wing.span == aircraft.wing.span
    assert result.aircraft.wing.root_chord == pytest.approx(2 / 3)
    assert result.aircraft.wing.tip_chord == pytest.approx(1 / 3)
    assert {change.parameter for change in result.changes} == {"wing.root_chord", "wing.tip_chord"}
    before, after = aircraft.model_dump(), result.aircraft.model_dump()
    before["wing"]["root_chord"] = after["wing"]["root_chord"]
    before["wing"]["tip_chord"] = after["wing"]["tip_chord"]
    assert before == after
    assert result.create_request.aircraft == result.aircraft
    assert {constraint.metric for constraint in result.create_request.constraints} == {
        "wing_area_m2",
        "wing_taper_ratio",
        "wing_root_chord_m",
        "wing_tip_chord_m",
    }


def test_projected_span_and_native_aspect_ratio_include_dihedral(aircraft: AircraftSpec) -> None:
    aircraft.wing.dihedral_deg = 30.0
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=_variables("span", "root_chord", "tip_chord"),
            targets={"projected_span_m": 4.0, "aspect_ratio": 8.0, "taper_ratio": 0.5},
        )
    )
    _assert_ready(result)
    assert result.aircraft.wing.span == pytest.approx(4 / math.cos(math.radians(30)))
    assert result.measurements["wing_projected_span_m"] == pytest.approx(4)
    assert result.measurements["wing_area_m2"] == pytest.approx(2)
    assert result.measurements["wing_aspect_ratio"] == pytest.approx(8)


def test_area_and_aspect_ratio_determine_span(aircraft: AircraftSpec) -> None:
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=_variables("span", "root_chord", "tip_chord"),
            targets={"area_m2": 3.0, "aspect_ratio": 10.0},
        )
    )
    _assert_ready(result)
    expected_span = math.sqrt(30) / math.cos(math.radians(aircraft.wing.dihedral_deg))
    assert result.aircraft.wing.span == pytest.approx(expected_span)
    assert result.measurements["wing_area_m2"] == pytest.approx(3)
    assert result.measurements["wing_aspect_ratio"] == pytest.approx(10)


def test_range_constraints_choose_baseline_nearest_feasible_dimensions(
    aircraft: AircraftSpec,
) -> None:
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=_variables("span", "root_chord", "tip_chord"),
            constraints=[
                {"metric": "wing_span_m", "maximum": 3.0},
                {"metric": "wing_area_m2", "minimum": 2.0},
                {"metric": "wing_taper_ratio", "minimum": 0.7, "maximum": 0.8},
                {"metric": "wing_root_chord_m", "maximum": 0.8},
            ],
        )
    )
    _assert_ready(result)
    assert result.aircraft.wing.span == 3
    assert result.measurements["wing_area_m2"] == pytest.approx(2)
    assert result.measurements["wing_taper_ratio"] == pytest.approx(0.7)
    assert result.aircraft.wing.root_chord <= 0.8


@pytest.mark.parametrize(
    "targets, constraints, adjustable",
    [
        ({"span_m": 5.0}, [], []),
        ({"span_m": 5.0}, [{"metric": "wing_span_m", "maximum": 3.0}], ["span"]),
        ({"area_m2": 5.0}, [], []),
        ({"taper_ratio": 0.01}, [], []),
        ({}, [{"metric": "fuselage_length_m", "minimum": 4.0}], ["span"]),
        ({}, [{"metric": "wing_area_m2", "maximum": 0.0}], ["span"]),
        ({}, [{"metric": "wing_root_chord_m", "minimum": 1.0}], []),
    ],
)
def test_conflicts_are_structured_without_candidate(
    aircraft: AircraftSpec, targets: dict, constraints: list, adjustable: list
) -> None:
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            targets=targets,
            constraints=constraints,
            adjustable=_variables(*adjustable),
        )
    )
    assert result.status == "infeasible"
    assert result.aircraft is None
    assert result.create_request is None
    assert result.measurements == {}
    assert result.changes == []
    assert result.diagnostics[0].code
    assert result.diagnostics[0].metrics


def test_bbox_constraints_are_deferred_and_preserved(aircraft: AircraftSpec) -> None:
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            constraints=[{"metric": "aircraft_y_extent_m", "maximum": 3.0}],
        )
    )
    _assert_ready(result)
    deferred = next(check for check in result.checks if check.status == "deferred")
    assert deferred.metric == "aircraft_y_extent_m"
    assert deferred.actual is None
    assert result.create_request.constraints[0].metric == "aircraft_y_extent_m"


def test_feet_variables_and_si_targets_have_explicit_units(aircraft: AircraftSpec) -> None:
    aircraft.units = "ft"
    for component in (
        aircraft.fuselage,
        aircraft.wing,
        aircraft.horizontal_tail,
        aircraft.vertical_tail,
    ):
        for field in ("length", "width", "height", "span", "root_chord", "tip_chord", "x_le", "z"):
            if hasattr(component, field):
                setattr(component, field, getattr(component, field) / 0.3048)
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=_variables("root_chord", "tip_chord"),
            targets={"area_m2": 2.0, "taper_ratio": 0.5},
        )
    )
    _assert_ready(result)
    assert result.aircraft.wing.root_chord == pytest.approx((2 / 3) / 0.3048)
    assert result.measurements["wing_area_m2"] == pytest.approx(2)
    assert all(change.units == "ft" for change in result.changes)
    root_bound = next(
        constraint
        for constraint in result.create_request.constraints
        if constraint.metric == "wing_root_chord_m"
    )
    assert root_bound.minimum == pytest.approx(0.1 * 0.3048)


def test_duplicate_variables_and_invalid_targets_rejected(aircraft: AircraftSpec) -> None:
    with pytest.raises(ValidationError, match="only once"):
        AircraftPlanRequest(aircraft=aircraft, adjustable=_variables("span", "span"))
    for value in (0, -1, math.inf, math.nan, True, "4"):
        with pytest.raises(ValidationError):
            AircraftPlanRequest(aircraft=aircraft, targets={"area_m2": value})


@pytest.mark.parametrize(
    "metric",
    [
        "wing_span_m",
        "wing_projected_span_m",
        "wing_area_m2",
        "wing_aspect_ratio",
        "wing_taper_ratio",
        "wing_root_chord_m",
        "wing_tip_chord_m",
    ],
)
def test_extreme_finite_bounds_are_structured(aircraft: AircraftSpec, metric: str) -> None:
    for bounds, expected in (
        ({"minimum": 1e308}, "infeasible"),
        ({"maximum": 1e-320}, "infeasible"),
        ({"minimum": -1e308, "maximum": 1e308}, "ready"),
    ):
        result = plan_aircraft(
            AircraftPlanRequest(aircraft=aircraft, constraints=[{"metric": metric, **bounds}])
        )
        assert result.status == expected
        assert all(math.isfinite(value) for value in result.measurements.values())


@pytest.mark.parametrize("taper", [1e-12, 1e12])
@pytest.mark.parametrize("units", ["m", "ft"])
def test_extreme_feasible_taper_avoids_chord_cancellation(
    aircraft: AircraftSpec, taper: float, units: str
) -> None:
    aircraft.units = units
    aircraft.wing.root_chord = 1e6 if taper < 1 else 1e-6
    aircraft.wing.tip_chord = 1e-6 if taper < 1 else 1e6
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=[
                {"parameter": "wing.root_chord", "minimum": 1e-6, "maximum": 1e6},
                {"parameter": "wing.tip_chord", "minimum": 1e-6, "maximum": 1e6},
            ],
            targets={"taper_ratio": taper},
        )
    )
    _assert_ready(result)
    assert result.measurements["wing_taper_ratio"] == pytest.approx(taper, rel=1e-14)


def test_only_tip_chord_adjustable_preserves_root_exactly(aircraft: AircraftSpec) -> None:
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=_variables("tip_chord"),
            targets={"area_m2": 2.0},
        )
    )
    _assert_ready(result)
    assert result.aircraft.wing.root_chord == aircraft.wing.root_chord
    assert result.aircraft.wing.span == aircraft.wing.span
    assert result.aircraft.wing.tip_chord == pytest.approx(0.35)


def test_consistent_exact_targets_are_not_overconstrained(aircraft: AircraftSpec) -> None:
    cosine = math.cos(math.radians(aircraft.wing.dihedral_deg))
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=_variables("span", "root_chord", "tip_chord"),
            targets={
                "span_m": 5.0,
                "projected_span_m": 5 * cosine,
                "area_m2": 3.0,
                "aspect_ratio": (5 * cosine) ** 2 / 3,
                "taper_ratio": 0.4,
            },
        )
    )
    _assert_ready(result)


@pytest.mark.parametrize("units", ["m", "ft"])
def test_exact_area_at_small_tip_lower_bound_avoids_false_infeasibility(
    aircraft: AircraftSpec, units: str
) -> None:
    aircraft.units = units
    aircraft.wing.span = 4.0
    aircraft.wing.root_chord = 2.0
    aircraft.wing.tip_chord = 0.5
    aircraft.wing.dihedral_deg = 0.0
    scale = 1.0 if units == "m" else 0.3048
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=[
                {"parameter": "wing.span", "minimum": 1.0, "maximum": 8.0},
                {"parameter": "wing.root_chord", "minimum": 1.0, "maximum": 3.0},
                {"parameter": "wing.tip_chord", "minimum": 0.001, "maximum": 1.0},
            ],
            targets={"area_m2": scale**2},
        )
    )
    _assert_ready(result)
    assert result.aircraft.wing.root_chord == 1.0
    assert result.aircraft.wing.tip_chord == 0.001
    assert abs(result.measurements["wing_area_m2"] - scale**2) <= 8 * math.ulp(scale**2)


@pytest.mark.parametrize("stage", ["intermediate", "final"])
def test_numerical_failure_is_unresolved_not_proven_infeasible(
    aircraft: AircraftSpec, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    def unresolved_solver(request):
        if stage == "intermediate":
            raise planning._Infeasible(
                "numerical_resolution_failure",
                "Precision could not resolve the bounds.",
                ["wing_span_m"],
            )
        return request.aircraft

    monkeypatch.setattr(planning, "_solve", unresolved_solver)
    result = plan_aircraft(
        AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=_variables("span"),
            targets={"span_m": 3.0},
        )
    )
    assert result.status == "unresolved"
    assert result.aircraft is None
    assert result.create_request is None
    assert result.diagnostics[0].code == "numerical_resolution_failure"


def test_deterministic_known_feasible_range_cases(aircraft: AircraftSpec) -> None:
    rng = random.Random(20261006)
    for _ in range(120):
        span, root, tip = [10 ** rng.uniform(-1, 1) for _ in range(3)]
        dihedral = rng.uniform(-75, 75)
        aircraft.wing.dihedral_deg = dihedral
        cosine = math.cos(math.radians(dihedral))
        values = {
            "wing_span_m": span,
            "wing_projected_span_m": span * cosine,
            "wing_area_m2": span * (root + tip) / 2,
            "wing_aspect_ratio": 2 * cosine**2 * span / (root + tip),
            "wing_taper_ratio": tip / root,
            "wing_root_chord_m": root,
            "wing_tip_chord_m": tip,
        }
        constraints = [
            {"metric": metric, "minimum": value * 0.95, "maximum": value * 1.05}
            for metric, value in values.items()
        ]
        request = AircraftPlanRequest(
            aircraft=aircraft,
            adjustable=[
                {"parameter": "wing.span", "minimum": span * 0.8, "maximum": span * 1.2},
                {"parameter": "wing.root_chord", "minimum": root * 0.8, "maximum": root * 1.2},
                {"parameter": "wing.tip_chord", "minimum": tip * 0.8, "maximum": tip * 1.2},
            ],
            constraints=constraints,
        )
        result = plan_aircraft(request)
        _assert_ready(result)
        selected = result.aircraft.wing
        actual = {
            "wing_span_m": selected.span,
            "wing_projected_span_m": selected.span * cosine,
            "wing_area_m2": selected.span * (selected.root_chord + selected.tip_chord) / 2,
            "wing_aspect_ratio": (
                (selected.span * cosine) ** 2
                / (selected.span * (selected.root_chord + selected.tip_chord) / 2)
            ),
            "wing_taper_ratio": selected.tip_chord / selected.root_chord,
            "wing_root_chord_m": selected.root_chord,
            "wing_tip_chord_m": selected.tip_chord,
        }
        for constraint in constraints:
            value = actual[constraint["metric"]]
            assert value >= constraint["minimum"] - 8 * math.ulp(constraint["minimum"])
            assert value <= constraint["maximum"] + 8 * math.ulp(constraint["maximum"])
        assert plan_aircraft(request) == result
