"""Typed revisions of verified managed aircraft snapshots."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from .aircraft import create_aircraft
from .models import (
    AircraftCreateRequest,
    AircraftCreateResponse,
    AircraftRevisionRequest,
    AircraftRevisionResponse,
    RevisedParameter,
)


class RevisionSourceError(RuntimeError):
    """A source bundle cannot safely be reconstructed from its specification."""


def _read_source(report_path: Path) -> tuple[AircraftCreateRequest, AircraftCreateResponse]:
    try:
        parent = AircraftCreateResponse.model_validate_json(report_path.read_bytes())
        specification = (report_path.parent / "specification.json").read_bytes()
        source = AircraftCreateRequest.model_validate_json(specification)
        geometry = (report_path.parent / f"{source.aircraft.name}.vsp3").read_bytes()
    except (OSError, ValidationError) as exc:
        raise RevisionSourceError(
            f"Invalid managed aircraft bundle at {report_path}: {exc}. "
            "Use report.json from the current create/revision tools and keep its sibling "
            "specification.json and .vsp3 together; older bundles must be rebuilt."
        ) from exc
    for label, content, expected in (
        ("specification", specification, parent.specification_sha256),
        ("geometry", geometry, parent.geometry_sha256),
    ):
        if hashlib.sha256(content).hexdigest() != expected:
            raise RevisionSourceError(
                f"Source {label} hash mismatch at {report_path.parent}; the managed snapshot "
                "has changed. Rebuild from the intended specification before typed revision."
            )
    return source, parent


def revise_aircraft(request: AircraftRevisionRequest) -> AircraftRevisionResponse:
    """Rebuild explicit parameter changes into a fresh run, preserving the parent."""
    report_path = Path(request.source_report_path).expanduser().resolve()
    source, parent = _read_source(report_path)
    payload = source.model_dump()
    changes = []
    for change in request.changes:
        component, field = change.parameter.split(".")
        before = payload["aircraft"][component][field]
        payload["aircraft"][component][field] = change.value
        units = (
            "deg"
            if field.endswith("_deg")
            else "dimensionless"
            if field == "thickness_ratio"
            else source.aircraft.units
        )
        changes.append(
            RevisedParameter(
                parameter=change.parameter, before=before, after=change.value, units=units
            )
        )
    if request.constraints is not None:
        payload["constraints"] = [constraint.model_dump() for constraint in request.constraints]
    payload["output_directory"] = request.output_directory or str(report_path.parent.parent)
    if request.timeout_seconds is not None:
        payload["timeout_seconds"] = request.timeout_seconds
    # Validate the complete layout; partial model_copy updates bypass model validators.
    candidate = AircraftCreateRequest.model_validate(payload)
    built = create_aircraft(
        candidate,
        provenance={
            "operation": "revision",
            "parent_candidate_id": parent.candidate_id,
            "parent_report_path": str(report_path),
            "parent_geometry_sha256": parent.geometry_sha256,
            "parent_specification_sha256": parent.specification_sha256,
            "revision_request": request.model_dump(mode="json"),
            "changes": [change.model_dump(mode="json") for change in changes],
        },
    )
    revision_request_path = Path(built.artifact_directory) / "revision_request.json"
    revision_request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    response = AircraftRevisionResponse(
        **built.model_dump(),
        parent_candidate_id=parent.candidate_id,
        parent_report_path=str(report_path),
        parent_geometry_sha256=parent.geometry_sha256,
        parent_specification_sha256=parent.specification_sha256,
        revision_request_path=str(revision_request_path),
        changes=changes,
    )
    Path(response.report_path).write_text(response.model_dump_json(indent=2), encoding="utf-8")
    return response
