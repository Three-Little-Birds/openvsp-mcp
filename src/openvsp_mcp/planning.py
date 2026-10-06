"""Analytical sizing of the conventional template without running OpenVSP."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import (
    AircraftCreateRequest,
    AircraftPlanRequest,
    AircraftPlanResponse,
    AircraftSpec,
    GeometryConstraint,
    PlannedDimensionChange,
    PlanningCheck,
    PlanningDiagnostic,
)

_TARGET_METRICS = {
    "span_m": "wing_span_m",
    "projected_span_m": "wing_projected_span_m",
    "area_m2": "wing_area_m2",
    "aspect_ratio": "wing_aspect_ratio",
    "taper_ratio": "wing_taper_ratio",
}
_DEFERRED_METRICS = {
    "aircraft_x_extent_m",
    "aircraft_y_extent_m",
    "aircraft_z_extent_m",
}
_PARAMETER_METRICS = {
    "wing.span": "wing_span_m",
    "wing.root_chord": "wing_root_chord_m",
    "wing.tip_chord": "wing_tip_chord_m",
}
_ASSUMPTIONS = [
    "Only explicitly adjustable wing span and chord dimensions may change; all other fields remain fixed.",
    "Wing area is developed trapezoidal area: span * (root_chord + tip_chord) / 2.",
    "Projected span is developed span * cos(dihedral); OpenVSP aspect ratio is projected_span^2 / developed_area.",
    "Selection preserves the baseline span when feasible, then the baseline chord sum, then minimizes squared chord changes at that sum.",
    "Bounds are inclusive with an eight-ULP floating-point roundoff allowance; targets are exact within that allowance.",
    "Planning is analytical; native geometry, bounding extents, attachments, and aerodynamics are not validated.",
]


def _roundoff(*values: float) -> float:
    return 8 * max(math.ulp(value) for value in values)


def _within(actual: float, minimum: float | None, maximum: float | None) -> bool:
    return (minimum is None or actual >= minimum - _roundoff(actual, minimum)) and (
        maximum is None or actual <= maximum + _roundoff(actual, maximum)
    )


class _Infeasible(Exception):
    def __init__(self, code: str, message: str, metrics: list[str]) -> None:
        super().__init__(message)
        self.diagnostic = PlanningDiagnostic(code=code, message=message, metrics=metrics)


@dataclass
class _Interval:
    minimum: float
    maximum: float
    metrics: list[str]

    def intersect(self, minimum: float, maximum: float, metric: str) -> None:
        self.minimum = max(self.minimum, minimum)
        self.maximum = min(self.maximum, maximum)
        self.metrics = list(dict.fromkeys([*self.metrics, metric]))
        if self.minimum > self.maximum + _roundoff(self.minimum, self.maximum):
            raise _Infeasible(
                "conflicting_bounds",
                f"No feasible interval: minimum {self.minimum:.17g} exceeds maximum {self.maximum:.17g}.",
                self.metrics,
            )

    def nearest(self, baseline: float) -> float:
        if self.minimum > self.maximum:
            return (self.minimum + self.maximum) / 2
        return min(self.maximum, max(self.minimum, baseline))


@dataclass(frozen=True)
class _Curve:
    coefficient: float
    power: int
    metric: str

    def evaluate(self, span: float) -> float:
        return self.coefficient * span**self.power


def _measure(spec: AircraftSpec) -> dict[str, float]:
    scale = 1.0 if spec.units == "m" else 0.3048
    wing = spec.wing
    span = wing.span * scale
    root = wing.root_chord * scale
    tip = wing.tip_chord * scale
    projected = span * math.cos(math.radians(wing.dihedral_deg))
    area = span * (root + tip) / 2
    return {
        "wing_span_m": span,
        "wing_root_chord_m": root,
        "wing_tip_chord_m": tip,
        "wing_projected_span_m": projected,
        "wing_area_m2": area,
        "wing_aspect_ratio": projected**2 / area,
        "wing_taper_ratio": tip / root,
        "fuselage_length_m": spec.fuselage.length * scale,
    }


def _deferred_checks(request: AircraftPlanRequest) -> list[PlanningCheck]:
    return [
        PlanningCheck(
            metric=constraint.metric,
            actual=None,
            minimum=constraint.minimum,
            maximum=constraint.maximum,
            status="deferred",
        )
        for constraint in request.constraints
        if constraint.metric in _DEFERRED_METRICS
    ]


def _checks(request: AircraftPlanRequest, measurements: dict[str, float]) -> list[PlanningCheck]:
    checks = []
    scale = 1.0 if request.aircraft.units == "m" else 0.3048
    adjustable = {variable.parameter: variable for variable in request.adjustable}
    for parameter, metric in _PARAMETER_METRICS.items():
        if parameter in adjustable:
            variable = adjustable[parameter]
            minimum, maximum = variable.minimum * scale, variable.maximum * scale
        else:
            value = getattr(request.aircraft.wing, parameter.split(".")[1]) * scale
            minimum = maximum = value
        actual = measurements[metric]
        checks.append(
            PlanningCheck(
                metric=metric,
                actual=actual,
                minimum=minimum,
                maximum=maximum,
                status="satisfied" if _within(actual, minimum, maximum) else "violated",
            )
        )
    for target, metric in _TARGET_METRICS.items():
        value = getattr(request.targets, target)
        if value is not None:
            actual = measurements[metric]
            checks.append(
                PlanningCheck(
                    metric=metric,
                    actual=actual,
                    minimum=value,
                    maximum=value,
                    status="satisfied" if _within(actual, value, value) else "violated",
                )
            )
    for constraint in request.constraints:
        if constraint.metric in _DEFERRED_METRICS:
            continue
        actual = measurements[constraint.metric]
        checks.append(
            PlanningCheck(
                metric=constraint.metric,
                actual=actual,
                minimum=constraint.minimum,
                maximum=constraint.maximum,
                status=(
                    "satisfied"
                    if _within(actual, constraint.minimum, constraint.maximum)
                    else "violated"
                ),
            )
        )
    return checks + _deferred_checks(request)


def _span_feasibility(span: _Interval, lower: list[_Curve], upper: list[_Curve]) -> None:
    for lo in lower:
        for hi in upper:
            power = lo.power - hi.power
            metrics = [lo.metric, hi.metric]
            if power == 0:
                if lo.coefficient > hi.coefficient + _roundoff(lo.coefficient, hi.coefficient):
                    raise _Infeasible(
                        "incompatible_wing_requirements",
                        f"Requirements {lo.metric} and {hi.metric} have incompatible chord-sum bounds.",
                        metrics,
                    )
            elif power > 0:
                limit = (hi.coefficient / lo.coefficient) ** (1 / power)
                span.intersect(0, limit, " / ".join(metrics))
            else:
                limit = (lo.coefficient / hi.coefficient) ** (1 / -power)
                span.intersect(limit, math.inf, " / ".join(metrics))


def _chord_sum_bounds(root: _Interval, tip: _Interval, taper: _Interval) -> tuple[float, float]:
    # Feasible chords form a convex polygon; a linear sum reaches its extrema at vertices.
    lines = [
        (1.0, 0.0, root.minimum),
        (1.0, 0.0, root.maximum),
        (0.0, 1.0, tip.minimum),
        (0.0, 1.0, tip.maximum),
        (-taper.minimum, 1.0, 0.0),
        (-taper.maximum, 1.0, 0.0),
    ]
    sums = []
    for index, (a, b, c) in enumerate(lines):
        for d, e, f in lines[index + 1 :]:
            determinant = a * e - b * d
            if determinant == 0:
                continue
            r = (c * e - b * f) / determinant
            t = (a * f - c * d) / determinant
            if (
                _within(r, root.minimum, root.maximum)
                and _within(t, tip.minimum, tip.maximum)
                and r > 0
                and _within(t / r, taper.minimum, taper.maximum)
            ):
                sums.append(r + t)
    if not sums:
        raise _Infeasible(
            "incompatible_chord_and_taper_bounds",
            "No positive root/tip chord pair satisfies the chord and taper bounds.",
            ["wing_root_chord_m", "wing_tip_chord_m", "wing_taper_ratio"],
        )
    return min(sums), max(sums)


def _split_chords(
    chord_sum: float, root: _Interval, tip: _Interval, taper: _Interval, spec: AircraftSpec
) -> tuple[float, float]:
    scale = 1.0 if spec.units == "m" else 0.3048
    root_baseline, tip_baseline = spec.wing.root_chord * scale, spec.wing.tip_chord * scale
    delta = (chord_sum - (root_baseline + tip_baseline)) / 2
    if taper.minimum == taper.maximum:
        ratio = taper.minimum
        return chord_sum / (1 + ratio), chord_sum * (ratio / (1 + ratio))
    # Compute the smaller chord directly to avoid cancellation for extreme taper ratios.
    interval = _Interval(
        max(root.minimum, chord_sum - tip.maximum, chord_sum / (1 + taper.maximum)),
        min(root.maximum, chord_sum - tip.minimum, chord_sum / (1 + taper.minimum)),
        ["wing.root_chord"],
    )
    selected_root = interval.nearest(root_baseline + delta)
    if selected_root <= chord_sum / 2:
        return selected_root, chord_sum - selected_root
    interval = _Interval(
        max(
            tip.minimum,
            chord_sum - root.maximum,
            chord_sum * (taper.minimum / (1 + taper.minimum)),
        ),
        min(
            tip.maximum,
            chord_sum - root.minimum,
            chord_sum * (taper.maximum / (1 + taper.maximum)),
        ),
        ["wing.tip_chord"],
    )
    selected_tip = interval.nearest(tip_baseline + delta)
    return chord_sum - selected_tip, selected_tip


def _solve(request: AircraftPlanRequest) -> AircraftSpec:
    spec = request.aircraft
    scale = 1.0 if spec.units == "m" else 0.3048
    adjustable = {variable.parameter: variable for variable in request.adjustable}
    bounds = {}
    for parameter in _PARAMETER_METRICS:
        baseline = getattr(spec.wing, parameter.split(".")[1]) * scale
        variable = adjustable.get(parameter)
        bounds[parameter] = _Interval(
            variable.minimum * scale if variable else baseline,
            variable.maximum * scale if variable else baseline,
            [parameter],
        )
    span = bounds["wing.span"]
    root = bounds["wing.root_chord"]
    tip = bounds["wing.tip_chord"]
    cosine = math.cos(math.radians(spec.wing.dihedral_deg))
    requirements = [
        (constraint.metric, constraint.minimum, constraint.maximum)
        for constraint in request.constraints
        if constraint.metric not in _DEFERRED_METRICS
    ]
    requirements += [
        (metric, value, value)
        for target, metric in _TARGET_METRICS.items()
        if (value := getattr(request.targets, target)) is not None
    ]
    for metric, minimum, maximum in requirements:
        if metric in {"wing_root_chord_m", "wing_tip_chord_m"}:
            chord = root if metric == "wing_root_chord_m" else tip
            chord.intersect(
                minimum if minimum is not None else 0,
                maximum if maximum is not None else math.inf,
                metric,
            )
    # Primitive bounds give safe finite ranges before multiplying arbitrary user constraints.
    metric_bounds = {
        "wing_area_m2": _Interval(
            span.minimum * (root.minimum + tip.minimum) / 2,
            span.maximum * (root.maximum + tip.maximum) / 2,
            ["wing_area_m2"],
        ),
        "wing_aspect_ratio": _Interval(
            2 * cosine**2 * span.minimum / (root.maximum + tip.maximum),
            2 * cosine**2 * span.maximum / (root.minimum + tip.minimum),
            ["wing_aspect_ratio"],
        ),
        "wing_taper_ratio": _Interval(
            tip.minimum / root.maximum,
            tip.maximum / root.minimum,
            ["wing_taper_ratio"],
        ),
    }
    for metric, minimum, maximum in requirements:
        if metric == "fuselage_length_m":
            actual = spec.fuselage.length * scale
            if not _within(actual, minimum, maximum):
                raise _Infeasible(
                    "fixed_dimension_conflict",
                    f"Fixed fuselage length {actual:.17g} m violates the requested bounds.",
                    [metric],
                )
        elif metric in {"wing_span_m", "wing_projected_span_m"}:
            factor = cosine if metric == "wing_projected_span_m" else 1
            effective = _Interval(span.minimum * factor, span.maximum * factor, [metric])
            effective.intersect(
                minimum if minimum is not None else 0,
                maximum if maximum is not None else math.inf,
                metric,
            )
            span.intersect(
                effective.minimum / factor,
                effective.maximum / factor,
                metric,
            )
        elif metric in metric_bounds:
            metric_bounds[metric].intersect(
                minimum if minimum is not None else 0,
                maximum if maximum is not None else math.inf,
                metric,
            )
    taper = metric_bounds["wing_taper_ratio"]
    sum_minimum, sum_maximum = _chord_sum_bounds(root, tip, taper)
    area = metric_bounds["wing_area_m2"]
    aspect_ratio = metric_bounds["wing_aspect_ratio"]
    lower = [
        _Curve(sum_minimum, 0, "wing.chord_and_taper_bounds"),
        _Curve(2 * area.minimum, -1, "wing_area_m2"),
        _Curve(2 * cosine**2 / aspect_ratio.maximum, 1, "wing_aspect_ratio"),
    ]
    upper = [
        _Curve(sum_maximum, 0, "wing.chord_and_taper_bounds"),
        _Curve(2 * area.maximum, -1, "wing_area_m2"),
        _Curve(2 * cosine**2 / aspect_ratio.minimum, 1, "wing_aspect_ratio"),
    ]
    _span_feasibility(span, lower, upper)
    selected_span = (
        span.nearest(spec.wing.span * scale)
        if "wing.span" in adjustable
        else spec.wing.span * scale
    )
    chord_sum = _Interval(
        max(curve.evaluate(selected_span) for curve in lower),
        min(curve.evaluate(selected_span) for curve in upper),
        ["wing.chord_sum"],
    )
    if chord_sum.minimum > chord_sum.maximum + _roundoff(chord_sum.minimum, chord_sum.maximum):
        raise _Infeasible(
            "numerical_resolution_failure",
            "Analytical bounds could not be resolved within floating-point precision.",
            chord_sum.metrics,
        )
    selected_sum = chord_sum.nearest((spec.wing.root_chord + spec.wing.tip_chord) * scale)
    selected_root, selected_tip = _split_chords(selected_sum, root, tip, taper, spec)
    # Subtraction can lose small-chord precision; snap using the sum's propagated roundoff.
    selected_chords = []
    for value, interval in ((selected_root, root), (selected_tip, tip)):
        if value < interval.minimum and interval.minimum - value <= _roundoff(
            value, interval.minimum, selected_sum
        ):
            value = interval.minimum
        if value > interval.maximum and value - interval.maximum <= _roundoff(
            value, interval.maximum, selected_sum
        ):
            value = interval.maximum
        selected_chords.append(value)
    selected_root, selected_tip = selected_chords
    selected = {"span": selected_span, "root_chord": selected_root, "tip_chord": selected_tip}
    payload = spec.model_dump()
    for field, value in selected.items():
        if f"wing.{field}" in adjustable:
            variable = adjustable[f"wing.{field}"]
            value /= scale
            if value < variable.minimum and _within(value, variable.minimum, None):
                value = variable.minimum
            if value > variable.maximum and _within(value, None, variable.maximum):
                value = variable.maximum
            payload["wing"][field] = value
    return AircraftSpec.model_validate(payload)


def _create_request(request: AircraftPlanRequest, aircraft: AircraftSpec) -> AircraftCreateRequest:
    constraints = list(request.constraints)
    constraints += [
        GeometryConstraint(metric=metric, minimum=value, maximum=value)
        for target, metric in _TARGET_METRICS.items()
        if (value := getattr(request.targets, target)) is not None
    ]
    scale = 1.0 if aircraft.units == "m" else 0.3048
    constraints += [
        GeometryConstraint(
            metric=_PARAMETER_METRICS[variable.parameter],
            minimum=variable.minimum * scale,
            maximum=variable.maximum * scale,
        )
        for variable in request.adjustable
    ]
    return AircraftCreateRequest(aircraft=aircraft, constraints=constraints)


def plan_aircraft(request: AircraftPlanRequest) -> AircraftPlanResponse:
    """Find a feasible bounded wing plan while preserving every fixed input field."""
    try:
        aircraft = _solve(request)
    except _Infeasible as error:
        return AircraftPlanResponse(
            status=(
                "unresolved"
                if error.diagnostic.code == "numerical_resolution_failure"
                else "infeasible"
            ),
            aircraft=None,
            create_request=None,
            measurements={},
            changes=[],
            checks=_deferred_checks(request),
            diagnostics=[error.diagnostic],
            assumptions=_ASSUMPTIONS,
        )
    measurements = _measure(aircraft)
    checks = _checks(request, measurements)
    failed = [check.metric for check in checks if check.status == "violated"]
    if failed:
        return AircraftPlanResponse(
            status="unresolved",
            aircraft=None,
            create_request=None,
            measurements={},
            changes=[],
            checks=_deferred_checks(request),
            diagnostics=[
                PlanningDiagnostic(
                    code="numerical_resolution_failure",
                    message="Computed dimensions failed the final analytical bounds check.",
                    metrics=failed,
                )
            ],
            assumptions=_ASSUMPTIONS,
        )
    changes = []
    for variable in request.adjustable:
        field = variable.parameter.split(".")[1]
        before, after = getattr(request.aircraft.wing, field), getattr(aircraft.wing, field)
        if before != after:
            changes.append(
                PlannedDimensionChange(
                    parameter=variable.parameter,
                    before=before,
                    after=after,
                    units=aircraft.units,
                )
            )
    return AircraftPlanResponse(
        status="ready",
        aircraft=aircraft,
        create_request=_create_request(request, aircraft),
        measurements=measurements,
        changes=changes,
        checks=checks,
        diagnostics=[],
        assumptions=_ASSUMPTIONS,
    )
