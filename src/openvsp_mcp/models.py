"""Typed request/response models for OpenVSP MCP calls."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class VSPCommand(BaseModel):
    """Single OpenVSP script command."""

    command: str = Field(..., description="Literal line inserted into the VSP script")


class OpenVSPGeometryRequest(BaseModel):
    geometry_file: str = Field(..., description="Path to the .vsp3 file")


class OpenVSPRequest(BaseModel):
    """Parameters controlling geometry edits and optional VSPAero run."""

    geometry_file: str = Field(..., description="Path to the .vsp3 file")
    set_commands: list[VSPCommand] = Field(default_factory=list, description="Commands to run")
    run_vspaero: bool = Field(True, description="Execute VSPAero after editing geometry")
    case_name: str = Field(
        "case", description="Path to a preconfigured VSPAero case base, without an extension"
    )
    output_directory: str | None = Field(
        None, description="Parent directory for retained run artifacts"
    )
    timeout_seconds: float = Field(300, gt=0, le=3600, allow_inf_nan=False)


class OpenVSPInspectResponse(BaseModel):
    """High-level summary of a geometry."""

    geom_ids: list[str] = Field(..., description="Top-level geometry IDs discovered")
    wing_names: list[str] = Field(default_factory=list, description="Detected wing geometry names")
    info_log: str = Field(..., description="Component ID, name, and type read from the saved model")
    components: list[GeometryComponent] = Field(default_factory=list)


class GeometryComponent(BaseModel):
    geom_id: str
    name: str
    type_name: str
    parameters: dict[str, dict[str, float]] = Field(default_factory=dict)


class OpenVSPResponse(BaseModel):
    """Response object capturing generated paths."""

    script_path: str = Field(..., description="Absolute path to the retained script file")
    result_path: str | None = Field(
        None,
        description="Path to the generated VSPAero .adb file (if run_vspaero=True)",
    )
    geometry_path: str = Field(..., description="Absolute path to the edited model")
    artifact_directory: str = Field(..., description="Retained scripts, model snapshot, and logs")


class FuselageSpec(StrictModel):
    length: float = Field(
        ..., ge=1e-6, le=1e6, strict=True, description="Nose-to-tail length in aircraft units"
    )
    width: float = Field(
        ...,
        ge=1e-6,
        le=1e6,
        strict=True,
        description="Width of the three elliptical interior stations",
    )
    height: float = Field(
        ...,
        ge=1e-6,
        le=1e6,
        strict=True,
        description="Height of the three elliptical interior stations",
    )


class LiftingSurfaceSpec(StrictModel):
    span: float = Field(
        ...,
        ge=1e-6,
        le=1e6,
        strict=True,
        description="Full developed span for wing/horizontal tail; root-to-tip height for vertical tail",
    )
    root_chord: float = Field(..., ge=1e-6, le=1e6, strict=True)
    tip_chord: float = Field(..., ge=1e-6, le=1e6, strict=True)
    x_le: float = Field(
        ..., ge=0, strict=True, description="Root leading-edge X from the fuselage nose"
    )
    z: float = Field(
        0, ge=-1e6, le=1e6, strict=True, description="Root leading-edge Z; positive upwards"
    )
    sweep_deg: float = Field(
        0, gt=-85, lt=85, strict=True, description="Quarter-chord sweep in degrees"
    )
    dihedral_deg: float = Field(0, gt=-85, lt=85, strict=True)
    incidence_deg: float = Field(
        0, ge=-30, le=30, strict=True, description="Root twist about the leading edge"
    )
    tip_twist_deg: float = Field(
        0, ge=-30, le=30, strict=True, description="Tip twist relative to root incidence"
    )
    thickness_ratio: float = Field(
        0.12,
        gt=0,
        le=0.4,
        strict=True,
        description="Symmetric NACA four-series t/c at root and tip",
    )


class AircraftSpec(StrictModel):
    name: str = Field("aircraft", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    units: Literal["m", "ft"] = Field(
        "m", description="Units for ALL input lengths; generated model uses metres"
    )
    fuselage: FuselageSpec
    wing: LiftingSurfaceSpec
    horizontal_tail: LiftingSurfaceSpec
    vertical_tail: LiftingSurfaceSpec

    @model_validator(mode="after")
    def validate_layout(self) -> AircraftSpec:
        for name in ("wing", "horizontal_tail", "vertical_tail"):
            if getattr(self, name).x_le >= self.fuselage.length:
                raise ValueError(f"{name}.x_le must lie before the fuselage tail")
        if self.vertical_tail.dihedral_deg != 0:
            raise ValueError("vertical_tail.dihedral_deg must be zero for an upright fin")
        return self


ConstraintMetric = Literal[
    "wing_span_m",
    "wing_projected_span_m",
    "wing_area_m2",
    "wing_aspect_ratio",
    "wing_taper_ratio",
    "wing_root_chord_m",
    "wing_tip_chord_m",
    "fuselage_length_m",
    "aircraft_x_extent_m",
    "aircraft_y_extent_m",
    "aircraft_z_extent_m",
]


class GeometryConstraint(StrictModel):
    metric: ConstraintMetric
    minimum: float | None = Field(None, strict=True)
    maximum: float | None = Field(None, strict=True)

    @model_validator(mode="after")
    def validate_bounds(self) -> GeometryConstraint:
        if self.minimum is None and self.maximum is None:
            raise ValueError("Supply at least one constraint bound")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class AircraftCreateRequest(StrictModel):
    aircraft: AircraftSpec
    constraints: list[GeometryConstraint] = Field(
        default_factory=list, description="Bounds use SI units regardless of input units"
    )
    output_directory: str | None = Field(
        None,
        description="Parent for a unique retained run directory; existing models are never overwritten",
    )
    timeout_seconds: float = Field(300, gt=0, le=3600, strict=True)
    relative_tolerance: float = Field(1e-6, ge=0, le=0.01, strict=True)
    absolute_tolerance: float = Field(
        1e-8, ge=0, le=0.01, strict=True, description="Tolerance in each checked quantity's units"
    )


class GeometryCheck(BaseModel):
    metric: str
    actual: float
    minimum: float | None
    maximum: float | None
    passed: bool


class AircraftCreateResponse(BaseModel):
    candidate_id: str
    builder_schema_version: Literal[1] = 1
    geometry_sha256: str
    specification_sha256: str
    geometry_path: str
    script_path: str
    specification_path: str
    report_path: str
    artifact_directory: str
    model_length_unit: Literal["m"] = "m"
    openvsp_version: str
    components: list[GeometryComponent]
    measurements: dict[str, float]
    validation_passed: bool
    checks: list[GeometryCheck]
    assumptions: list[str]


WingDimension = Literal["wing.span", "wing.root_chord", "wing.tip_chord"]


class AdjustableWingDimension(StrictModel):
    parameter: WingDimension
    minimum: float = Field(..., ge=1e-6, le=1e6, strict=True)
    maximum: float = Field(..., ge=1e-6, le=1e6, strict=True)

    @model_validator(mode="after")
    def validate_bounds(self) -> AdjustableWingDimension:
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class WingSizingTargets(StrictModel):
    span_m: float | None = Field(None, gt=0, le=1e6, strict=True)
    projected_span_m: float | None = Field(None, gt=0, le=1e6, strict=True)
    area_m2: float | None = Field(None, gt=0, le=1e12, strict=True)
    aspect_ratio: float | None = Field(None, gt=0, le=1e12, strict=True)
    taper_ratio: float | None = Field(None, gt=0, le=1e12, strict=True)


class AircraftPlanRequest(StrictModel):
    aircraft: AircraftSpec
    adjustable: list[AdjustableWingDimension] = Field(
        default_factory=list,
        description="Only listed wing dimensions may change; bounds use aircraft.units",
    )
    targets: WingSizingTargets = Field(default_factory=WingSizingTargets)
    constraints: list[GeometryConstraint] = Field(
        default_factory=list, description="Bounds use SI, including when aircraft.units is ft"
    )

    @model_validator(mode="after")
    def validate_variables(self) -> AircraftPlanRequest:
        parameters = [variable.parameter for variable in self.adjustable]
        if len(set(parameters)) != len(parameters):
            raise ValueError("Each adjustable parameter must appear only once")
        return self


class PlannedDimensionChange(BaseModel):
    parameter: WingDimension
    before: float
    after: float
    units: Literal["m", "ft"]


class PlanningCheck(BaseModel):
    metric: str
    actual: float | None
    minimum: float | None
    maximum: float | None
    status: Literal["satisfied", "violated", "deferred"]


class PlanningDiagnostic(BaseModel):
    code: str
    message: str
    metrics: list[str] = Field(default_factory=list)


class AircraftPlanResponse(BaseModel):
    status: Literal["ready", "infeasible", "unresolved"]
    aircraft: AircraftSpec | None
    create_request: AircraftCreateRequest | None
    measurements: dict[str, float]
    changes: list[PlannedDimensionChange]
    checks: list[PlanningCheck]
    diagnostics: list[PlanningDiagnostic]
    assumptions: list[str]


AircraftParameter = Literal[
    "fuselage.length",
    "fuselage.width",
    "fuselage.height",
    "wing.span",
    "wing.root_chord",
    "wing.tip_chord",
    "wing.x_le",
    "wing.z",
    "wing.sweep_deg",
    "wing.dihedral_deg",
    "wing.incidence_deg",
    "wing.tip_twist_deg",
    "wing.thickness_ratio",
    "horizontal_tail.span",
    "horizontal_tail.root_chord",
    "horizontal_tail.tip_chord",
    "horizontal_tail.x_le",
    "horizontal_tail.z",
    "horizontal_tail.sweep_deg",
    "horizontal_tail.dihedral_deg",
    "horizontal_tail.incidence_deg",
    "horizontal_tail.tip_twist_deg",
    "horizontal_tail.thickness_ratio",
    "vertical_tail.span",
    "vertical_tail.root_chord",
    "vertical_tail.tip_chord",
    "vertical_tail.x_le",
    "vertical_tail.z",
    "vertical_tail.sweep_deg",
    "vertical_tail.dihedral_deg",
    "vertical_tail.incidence_deg",
    "vertical_tail.tip_twist_deg",
    "vertical_tail.thickness_ratio",
]


class AircraftParameterChange(StrictModel):
    parameter: AircraftParameter
    value: float = Field(..., strict=True, description="Lengths use the parent's aircraft.units")


class AircraftRevisionRequest(StrictModel):
    source_report_path: str = Field(
        ...,
        description="report.json from a managed create/revision run; source hashes are verified",
    )
    changes: list[AircraftParameterChange] = Field(..., min_length=1)
    constraints: list[GeometryConstraint] | None = Field(
        None, description="null inherits parent constraints; [] explicitly clears them"
    )
    output_directory: str | None = Field(
        None, description="Parent for the new run; default is the source run's parent directory"
    )
    timeout_seconds: float | None = Field(None, gt=0, le=3600, strict=True)

    @model_validator(mode="after")
    def validate_changes(self) -> AircraftRevisionRequest:
        parameters = [change.parameter for change in self.changes]
        if len(set(parameters)) != len(parameters):
            raise ValueError("Each changed parameter must appear only once")
        return self


class RevisedParameter(BaseModel):
    parameter: AircraftParameter
    before: float
    after: float
    units: Literal["m", "ft", "deg", "dimensionless"]


class AircraftRevisionResponse(AircraftCreateResponse):
    parent_candidate_id: str
    parent_report_path: str
    parent_geometry_sha256: str
    parent_specification_sha256: str
    revision_request_path: str
    changes: list[RevisedParameter]
