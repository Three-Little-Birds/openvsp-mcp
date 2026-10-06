from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_describe_cli_outputs_metadata() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "openvsp_mcp", "--describe"],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    payload = json.loads(result.stdout)
    assert payload["name"] == "openvsp-mcp"
    assert payload["default_transport"] == "stdio"
    tools = {tool["name"]: tool for tool in payload["tools"]}
    assert "openvsp_create_aircraft" in tools
    assert tools["openvsp_plan_aircraft"]["annotations"]["readOnlyHint"]
    assert tools["openvsp_plan_aircraft"]["annotations"]["idempotentHint"]
    assert tools["openvsp_update_aircraft"]["annotations"]["destructiveHint"] is False
    assert tools["openvsp_update_aircraft"]["outputSchema"] is not None
    assert tools["openvsp.inspect"]["annotations"]["readOnlyHint"]
