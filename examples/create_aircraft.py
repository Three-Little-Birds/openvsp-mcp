"""Build the dimensioned example and print its native validation report."""

from __future__ import annotations

import json
from pathlib import Path

from openvsp_mcp import AircraftCreateRequest, create_aircraft

if __name__ == "__main__":
    specification = Path(__file__).with_name("conventional_aircraft.json")
    request = AircraftCreateRequest.model_validate_json(specification.read_text(encoding="utf-8"))
    response = create_aircraft(request)
    print(json.dumps(response.model_dump(mode="json"), indent=2))
    raise SystemExit(0 if response.validation_passed else 1)
