"""Read saved OpenVSP parameters without executing or changing the model."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .models import GeometryComponent, OpenVSPInspectResponse


def read_geometry_root(geometry_file: str | Path) -> ET.Element:
    try:
        root = ET.parse(Path(geometry_file).expanduser()).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RuntimeError(f"Cannot read OpenVSP model {geometry_file}: {exc}") from exc
    if root.tag != "Vsp_Geometry":
        raise RuntimeError(f"Not an OpenVSP .vsp3 model: {geometry_file}")
    return root


def describe_geometry(geometry_file: str) -> OpenVSPInspectResponse:
    root = read_geometry_root(geometry_file)
    components = []
    for geom in root.findall("Vehicle/Geom"):
        parameters = {}
        container = geom.find("ParmContainer")
        if container is not None:
            for group in container:
                values = {
                    parm.tag: float(parm.attrib["Value"])
                    for parm in group
                    if "Value" in parm.attrib
                }
                if values:
                    parameters[group.tag] = values
        components.append(
            GeometryComponent(
                geom_id=geom.findtext("ParmContainer/ID", ""),
                name=geom.findtext("ParmContainer/Name", ""),
                type_name=geom.findtext("GeomBase/TypeName", ""),
                parameters=parameters,
            )
        )
    return OpenVSPInspectResponse(
        geom_ids=[component.geom_id for component in components if component.geom_id],
        wing_names=[
            component.name for component in components if component.type_name.lower() == "wing"
        ],
        info_log="\n".join(
            f"{component.geom_id}:{component.name}:{component.type_name}"
            for component in components
        ),
        components=components,
    )
