"""Repair a constrained candidate using analytical sizing and a typed revision."""

from pathlib import Path

from openvsp_mcp import (
    AircraftCreateRequest,
    AircraftPlanRequest,
    AircraftRevisionRequest,
    create_aircraft,
    plan_aircraft,
    revise_aircraft,
)


def main() -> None:
    baseline = AircraftCreateRequest.model_validate_json(
        Path(__file__).with_name("conventional_aircraft.json").read_text()
    )
    payload = baseline.model_dump()
    payload["constraints"] = [
        {"metric": "wing_span_m", "maximum": 3.5},
        {"metric": "wing_area_m2", "minimum": 1.6, "maximum": 1.7},
    ]
    baseline = AircraftCreateRequest.model_validate(payload)
    parent = create_aircraft(baseline)
    plan = plan_aircraft(
        AircraftPlanRequest(
            aircraft=baseline.aircraft,
            adjustable=[
                {"parameter": "wing.span", "minimum": 3.0, "maximum": 3.5},
                {"parameter": "wing.root_chord", "minimum": 0.4, "maximum": 0.8},
                {"parameter": "wing.tip_chord", "minimum": 0.2, "maximum": 0.4},
            ],
            targets={"area_m2": 1.65, "taper_ratio": 0.5},
            constraints=baseline.constraints,
        )
    )
    if plan.status != "ready":
        raise RuntimeError(f"Sizing is infeasible: {plan.diagnostics}")
    revised = revise_aircraft(
        AircraftRevisionRequest(
            source_report_path=parent.report_path,
            changes=[
                {"parameter": change.parameter, "value": change.after} for change in plan.changes
            ],
            constraints=plan.create_request.constraints,
        )
    )
    print(
        f"Parent passed: {parent.validation_passed}; revision passed: {revised.validation_passed}"
    )
    print(revised.geometry_path)
    if not revised.validation_passed:
        raise RuntimeError([check.model_dump() for check in revised.checks if not check.passed])


if __name__ == "__main__":
    main()
