from __future__ import annotations

import json
import subprocess
import sys


def test_describe_cli_outputs_metadata() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "openvsp_mcp", "--describe"],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["name"] == "openvsp-mcp"
    assert payload["default_transport"] == "stdio"
