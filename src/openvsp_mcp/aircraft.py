"""Deterministic conventional aircraft construction and native parameter verification."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

from .core import create_run_directory, run_openvsp, write_model_script
from .describe import describe_geometry, read_geometry_root
from .models import (
    AircraftCreateRequest,
    AircraftCreateResponse,
    AircraftSpec,
    GeometryCheck,
    LiftingSurfaceSpec,
)

SURFACE_NAMES = {
    "wing": "Wing",
    "horizontal_tail": "HorizontalTail",
    "vertical_tail": "VerticalTail",
}
ASSUMPTIONS = [
    "Conventional layout: one fuselage, one wing, one horizontal tail, one upright fin.",
    "Single trapezoidal section per lifting surface, with symmetric NACA four-series airfoils.",
    "Horizontal spans are full developed spans; fin span is root-to-tip height.",
    "Sweep is measured at quarter chord; incidence and tip twist rotate about the leading edge.",
    "Fuselage uses point ends and equal elliptical sections at 25%, 50%, and 75% length.",
    "OpenVSP coordinates: X aft from nose, Y lateral, Z up; model lengths are metres.",
    "Checks cover saved dimensions and bounding extents; aerodynamic stability, clearance, and watertightness are not evaluated.",
]


def _set(variable: str, name: str, group: str, value: float) -> str:
    return f'SetParmVal({variable}, "{name}", "{group}", {value:.17g});'


def _surface_commands(key: str, surface: LiftingSurfaceSpec, scale: float) -> list[str]:
    vertical = key == "vertical_tail"
    section_span = surface.span * scale / (1 if vertical else 2)
    commands = [
        f'string {key} = AddGeom("WING", "");',
        f'SetGeomName({key}, "{SURFACE_NAMES[key]}");',
        _set(key, "Sym_Planar_Flag", "Sym", 0 if vertical else 2),
        f"SetDriverGroup({key}, 1, SPAN_WSECT_DRIVER, ROOTC_WSECT_DRIVER, TIPC_WSECT_DRIVER);",
        _set(key, "Span", "XSec_1", section_span),
        _set(key, "Root_Chord", "XSec_1", surface.root_chord * scale),
        _set(key, "Tip_Chord", "XSec_1", surface.tip_chord * scale),
        _set(key, "Sweep_Location", "XSec_1", 0.25),
        _set(key, "Sweep", "XSec_1", surface.sweep_deg),
        _set(key, "Dihedral", "XSec_1", surface.dihedral_deg),
        _set(key, "RelativeTwistFlag", "WingGeom", 0),
        _set(key, "Twist", "XSec_0", surface.incidence_deg),
        _set(key, "Twist", "XSec_1", surface.incidence_deg + surface.tip_twist_deg),
        _set(key, "Twist_Location", "XSec_0", 0),
        _set(key, "Twist_Location", "XSec_1", 0),
        _set(key, "X_Rel_Location", "XForm", surface.x_le * scale),
        _set(key, "Z_Rel_Location", "XForm", surface.z * scale),
        _set(key, "X_Rel_Rotation", "XForm", 90 if vertical else 0),
    ]
    for index in range(2):
        commands += [
            _set(key, "Camber", f"XSecCurve_{index}", 0),
            _set(key, "ThickChord", f"XSecCurve_{index}", surface.thickness_ratio),
        ]
    commands.append("Update();")
    return commands


def aircraft_commands(spec: AircraftSpec) -> list[str]:
    scale = 1.0 if spec.units == "m" else 0.3048
    commands = [
        'string fuselage = AddGeom("FUSELAGE", "");',
        'SetGeomName(fuselage, "Fuselage");',
        _set("fuselage", "Length", "Design", spec.fuselage.length * scale),
        _set("fuselage", "Sym_Planar_Flag", "Sym", 0),
        "string fuselage_surf = GetXSecSurf(fuselage, 0);",
    ]
    for index in range(1, 4):
        commands.append(_set("fuselage", "XLocPercent", f"XSec_{index}", index / 4))
        commands.append(
            f"SetXSecWidthHeight(GetXSec(fuselage_surf, {index}), "
            f"{spec.fuselage.width * scale:.17g}, {spec.fuselage.height * scale:.17g});"
        )
    commands.append("Update();")
    for key in SURFACE_NAMES:
        commands.extend(_surface_commands(key, getattr(spec, key), scale))
    return commands


def _value(element: ET.Element, path: str) -> float:
    parm = element.find(path)
    if parm is None or "Value" not in parm.attrib:
        raise RuntimeError(f"Native model is missing parameter {path}")
    value = float(parm.attrib["Value"])
    if not math.isfinite(value):
        raise RuntimeError(f"Native model contains nonfinite parameter {path}")
    return value


def measure_aircraft(geometry_path: Path) -> dict[str, float]:
    root = read_geometry_root(geometry_path)
    elements = root.findall("Vehicle/Geom")
    geoms = {geom.findtext("ParmContainer/Name"): geom for geom in elements}
    if len(elements) != 4 or set(geoms) != {"Fuselage", *SURFACE_NAMES.values()}:
        raise RuntimeError(f"Expected four aircraft components, got {list(geoms)}")
    measurements = {"fuselage_length_m": _value(geoms["Fuselage"], "ParmContainer/Design/Length")}
    for key, name in SURFACE_NAMES.items():
        geom = geoms[name]
        for metric, parm in (
            ("span_m", "TotalSpan"),
            ("projected_span_m", "TotalProjectedSpan"),
            ("area_m2", "TotalArea"),
            ("aspect_ratio", "TotalAR"),
        ):
            measurements[f"{key}_{metric}"] = _value(geom, f"ParmContainer/WingGeom/{parm}")
        for metric, parm in (
            ("x_le_m", "X_Rel_Location"),
            ("z_m", "Z_Rel_Location"),
            ("x_rotation_deg", "X_Rel_Rotation"),
        ):
            measurements[f"{key}_{metric}"] = _value(geom, f"ParmContainer/XForm/{parm}")
        measurements[f"{key}_symmetry_flag"] = _value(geom, "ParmContainer/Sym/Sym_Planar_Flag")
        sections = geom.findall("WingGeom/XSecSurf/XSec")
        if len(sections) != 2:
            raise RuntimeError(f"{name} should have two airfoil stations, got {len(sections)}")
        for metric, parm in (
            ("root_chord_m", "Root_Chord"),
            ("tip_chord_m", "Tip_Chord"),
            ("sweep_deg", "Sweep"),
            ("dihedral_deg", "Dihedral"),
            ("tip_twist_deg", "Twist"),
            ("sweep_location", "Sweep_Location"),
        ):
            measurements[f"{key}_{metric}"] = _value(sections[1], f"ParmContainer/XSec/{parm}")
        measurements[f"{key}_root_twist_deg"] = _value(sections[0], "ParmContainer/XSec/Twist")
        measurements[f"{key}_taper_ratio"] = (
            measurements[f"{key}_tip_chord_m"] / measurements[f"{key}_root_chord_m"]
        )
        for index, section in enumerate(sections):
            measurements[f"{key}_thickness_ratio_{index}"] = _value(
                section, "XSec/XSecCurve/ParmContainer/XSecCurve/ThickChord"
            )
    fuselage_sections = geoms["Fuselage"].findall("FuselageGeom/XSecSurf/XSec")
    if len(fuselage_sections) != 5:
        raise RuntimeError("Expected five fuselage stations")
    for index in range(1, 4):
        measurements[f"fuselage_station_{index}_x_fraction"] = _value(
            fuselage_sections[index], "ParmContainer/XSec/XLocPercent"
        )
        for metric, parm in (("width", "Ellipse_Width"), ("height", "Ellipse_Height")):
            measurements[f"fuselage_station_{index}_{metric}_m"] = _value(
                fuselage_sections[index], f"XSec/XSecCurve/ParmContainer/XSecCurve/{parm}"
            )
    for axis in "XYZ":
        minima = [_value(geom, f"ParmContainer/BBox/{axis}_Min") for geom in geoms.values()]
        maxima = [
            minimum + _value(geom, f"ParmContainer/BBox/{axis}_Len")
            for minimum, geom in zip(minima, geoms.values(), strict=True)
        ]
        measurements[f"aircraft_{axis.lower()}_extent_m"] = max(maxima) - min(minima)
    return measurements


def expected_measurements(spec: AircraftSpec) -> dict[str, float]:
    scale = 1.0 if spec.units == "m" else 0.3048
    expected = {"fuselage_length_m": spec.fuselage.length * scale}
    for index in range(1, 4):
        expected[f"fuselage_station_{index}_x_fraction"] = index / 4
        expected[f"fuselage_station_{index}_width_m"] = spec.fuselage.width * scale
        expected[f"fuselage_station_{index}_height_m"] = spec.fuselage.height * scale
    for key in SURFACE_NAMES:
        surface = getattr(spec, key)
        area = surface.span * (surface.root_chord + surface.tip_chord) * scale**2 / 2
        projected_span = surface.span * scale * math.cos(math.radians(surface.dihedral_deg))
        expected.update(
            {
                f"{key}_span_m": surface.span * scale,
                f"{key}_area_m2": area,
                f"{key}_projected_span_m": projected_span,
                f"{key}_aspect_ratio": projected_span**2 / area,
                f"{key}_taper_ratio": surface.tip_chord / surface.root_chord,
                f"{key}_root_chord_m": surface.root_chord * scale,
                f"{key}_tip_chord_m": surface.tip_chord * scale,
                f"{key}_x_le_m": surface.x_le * scale,
                f"{key}_z_m": surface.z * scale,
                f"{key}_sweep_deg": surface.sweep_deg,
                f"{key}_dihedral_deg": surface.dihedral_deg,
                f"{key}_root_twist_deg": surface.incidence_deg,
                f"{key}_tip_twist_deg": surface.incidence_deg + surface.tip_twist_deg,
                f"{key}_sweep_location": 0.25,
                f"{key}_x_rotation_deg": 90 if key == "vertical_tail" else 0,
                f"{key}_symmetry_flag": 0 if key == "vertical_tail" else 2,
                f"{key}_thickness_ratio_0": surface.thickness_ratio,
                f"{key}_thickness_ratio_1": surface.thickness_ratio,
            }
        )
    return expected


def _within_bound(actual: float, bound: float, lower: bool) -> bool:
    satisfied = actual >= bound if lower else actual <= bound
    roundoff = 8 * max(math.ulp(actual), math.ulp(bound))
    return satisfied or abs(actual - bound) <= roundoff


def validate_measurements(
    request: AircraftCreateRequest, measurements: dict[str, float]
) -> list[GeometryCheck]:
    checks = []
    for metric, target in expected_measurements(request.aircraft).items():
        tolerance = request.absolute_tolerance + request.relative_tolerance * abs(target)
        actual = measurements[metric]
        checks.append(
            GeometryCheck(
                metric=metric,
                actual=actual,
                minimum=target - tolerance,
                maximum=target + tolerance,
                passed=abs(actual - target) <= tolerance,
            )
        )
    for constraint in request.constraints:
        actual = measurements[constraint.metric]
        minimum = constraint.minimum
        maximum = constraint.maximum
        checks.append(
            GeometryCheck(
                metric=constraint.metric,
                actual=actual,
                minimum=minimum,
                maximum=maximum,
                passed=(minimum is None or _within_bound(actual, minimum, lower=True))
                and (maximum is None or _within_bound(actual, maximum, lower=False)),
            )
        )
    return checks


def create_aircraft(
    request: AircraftCreateRequest, *, provenance: dict[str, object] | None = None
) -> AircraftCreateResponse:
    """Build a managed snapshot, retaining optional provenance before native execution."""
    workdir = create_run_directory(request.output_directory)
    geometry_path = workdir / f"{request.aircraft.name}.vsp3"
    specification_path = workdir / "specification.json"
    specification_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    if provenance is not None:
        (workdir / "provenance.json").write_text(
            json.dumps(provenance, indent=2, allow_nan=False), encoding="utf-8"
        )
    script_path = write_model_script(
        aircraft_commands(request.aircraft), workdir / "build.vspscript", geometry_path
    )
    version = run_openvsp(script_path, geometry_path, request.timeout_seconds)
    measurements = measure_aircraft(geometry_path)
    checks = validate_measurements(request, measurements)
    report_path = workdir / "report.json"
    response = AircraftCreateResponse(
        candidate_id=uuid.uuid4().hex,
        geometry_sha256=hashlib.sha256(geometry_path.read_bytes()).hexdigest(),
        specification_sha256=hashlib.sha256(specification_path.read_bytes()).hexdigest(),
        geometry_path=str(geometry_path),
        script_path=str(script_path),
        specification_path=str(specification_path),
        report_path=str(report_path),
        artifact_directory=str(workdir),
        openvsp_version=version,
        components=describe_geometry(str(geometry_path)).components,
        measurements=measurements,
        validation_passed=all(check.passed for check in checks),
        checks=checks,
        assumptions=ASSUMPTIONS,
    )
    report_path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
    return response
