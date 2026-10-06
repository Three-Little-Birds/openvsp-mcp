from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP

from openvsp_mcp.fastapi_app import create_app
from openvsp_mcp.models import AircraftSpec
from openvsp_mcp.tool import build_tool

ROOT = Path(__file__).parents[1]


def planning_payload() -> dict:
    aircraft = json.loads((ROOT / "examples/conventional_aircraft.json").read_text())["aircraft"]
    aircraft["wing"]["dihedral_deg"] = 0
    return {
        "aircraft": aircraft,
        "adjustable": [
            {"parameter": "wing.root_chord", "minimum": 0.1, "maximum": 1.5},
            {"parameter": "wing.tip_chord", "minimum": 0.1, "maximum": 1.5},
        ],
        "targets": {"area_m2": 2, "taper_ratio": 0.5},
        "constraints": [{"metric": "aircraft_x_extent_m", "maximum": 3.1}],
    }


def test_stdio_initialize_discover_plan_inspect_and_invalid_create() -> None:
    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "openvsp_mcp"],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            build = next(tool for tool in tools if tool.name == "openvsp_create_aircraft")
            assert build.inputSchema["$defs"]["AircraftSpec"]["additionalProperties"] is False
            assert build.outputSchema is not None
            planner = next(tool for tool in tools if tool.name == "openvsp_plan_aircraft")
            assert planner.annotations.readOnlyHint is True
            assert planner.annotations.idempotentHint is True
            assert planner.outputSchema is not None
            revision = next(tool for tool in tools if tool.name == "openvsp_update_aircraft")
            assert revision.annotations.readOnlyHint is False
            assert revision.annotations.destructiveHint is False
            assert (
                revision.inputSchema["$defs"]["AircraftParameterChange"]["additionalProperties"]
                is False
            )
            payload = planning_payload()
            planned = await session.call_tool("openvsp_plan_aircraft", {"request": payload})
            assert not planned.isError
            plan = planned.structuredContent
            assert plan["status"] == "ready"
            assert plan["aircraft"]["wing"]["root_chord"] == pytest.approx(2 / 3)
            assert plan["aircraft"]["wing"]["tip_chord"] == pytest.approx(1 / 3)
            assert plan["create_request"]["aircraft"] == plan["aircraft"]
            assert any(check["status"] == "deferred" for check in plan["checks"])
            payload["targets"]["span_m"] = 5
            incompatible = await session.call_tool("openvsp_plan_aircraft", {"request": payload})
            assert not incompatible.isError
            assert incompatible.structuredContent["status"] == "infeasible"
            assert incompatible.structuredContent["create_request"] is None
            assert incompatible.structuredContent["diagnostics"]
            result = await session.call_tool(
                "openvsp.inspect",
                {"request": {"geometry_file": str(ROOT / "src/openvsp_mcp/data/rect_wing.vsp3")}},
            )
            assert not result.isError
            assert result.structuredContent["wing_names"] == ["RectWing"]
            invalid = await session.call_tool(
                "openvsp_create_aircraft", {"request": {"aircraft": {}}}
            )
            assert invalid.isError

    asyncio.run(run())


def test_streamable_http_initialize_discover_plan_and_inspect() -> None:
    app = FastMCP("test", stateless_http=True, json_response=True)
    build_tool(app)
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app.streamable_http_app(), base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert "tools" in response.json()["result"]["capabilities"]
        headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
        response = client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        tools = response.json()["result"]["tools"]
        inspect = next(tool for tool in tools if tool["name"] == "openvsp.inspect")
        assert inspect["annotations"]["readOnlyHint"] is True
        planner = next(tool for tool in tools if tool["name"] == "openvsp_plan_aircraft")
        assert planner["annotations"]["readOnlyHint"] is True
        assert (
            planner["inputSchema"]["$defs"]["AircraftPlanRequest"]["additionalProperties"] is False
        )
        revision = next(tool for tool in tools if tool["name"] == "openvsp_update_aircraft")
        assert revision["annotations"]["destructiveHint"] is False
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "openvsp.inspect",
                    "arguments": {
                        "request": {
                            "geometry_file": str(ROOT / "src/openvsp_mcp/data/rect_wing.vsp3")
                        }
                    },
                },
            },
        )
        assert response.json()["result"]["structuredContent"]["wing_names"] == ["RectWing"]
        for request_id, payload, expected_status in (
            (4, planning_payload(), "ready"),
            (5, {**planning_payload(), "targets": {"span_m": 5}}, "infeasible"),
        ):
            response = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {
                        "name": "openvsp_plan_aircraft",
                        "arguments": {"request": payload},
                    },
                },
            )
            result = response.json()["result"]
            assert not result["isError"]
            assert result["structuredContent"]["status"] == expected_status


@pytest.mark.skipif(
    not os.environ.get("OPENVSP_BIN"), reason="Set OPENVSP_BIN to run native integration tests"
)
def test_stdio_plan_build_and_revision_preserve_parent(tmp_path: Path) -> None:
    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "openvsp_mcp"],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            planned = await session.call_tool(
                "openvsp_plan_aircraft", {"request": planning_payload()}
            )
            assert not planned.isError
            request = planned.structuredContent["create_request"]
            request["output_directory"] = str(tmp_path)
            built = await session.call_tool("openvsp_create_aircraft", {"request": request})
            assert not built.isError
            parent = built.structuredContent
            assert parent["validation_passed"]
            parent_files = {
                key: Path(parent[key]).read_bytes()
                for key in ("geometry_path", "specification_path", "report_path")
            }
            updated = await session.call_tool(
                "openvsp_update_aircraft",
                {
                    "request": {
                        "source_report_path": parent["report_path"],
                        "changes": [{"parameter": "wing.z", "value": 0.11}],
                    }
                },
            )
            assert not updated.isError
            revision = updated.structuredContent
            assert revision["validation_passed"]
            assert revision["candidate_id"] != parent["candidate_id"]
            assert revision["parent_candidate_id"] == parent["candidate_id"]
            assert revision["parent_geometry_sha256"] == parent["geometry_sha256"]
            assert revision["measurements"]["wing_z_m"] == pytest.approx(0.11)
            rejected = await session.call_tool(
                "openvsp_update_aircraft",
                {
                    "request": {
                        "source_report_path": parent["report_path"],
                        "changes": [{"parameter": "fuselage.length", "value": 1}],
                    }
                },
            )
            assert rejected.isError
            for key, content in parent_files.items():
                assert Path(parent[key]).read_bytes() == content

    asyncio.run(run())


def test_rest_plan_and_revision_error_responses(monkeypatch) -> None:
    client = TestClient(create_app())
    response = client.post("/vsp/aircraft/plan", json=planning_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["create_request"]["aircraft"]["wing"]["root_chord"] == pytest.approx(
        2 / 3
    )
    response = client.post(
        "/vsp/aircraft/revise",
        json={
            "source_report_path": "/missing/openvsp/report.json",
            "changes": [{"parameter": "wing.span", "value": 4.2}],
        },
    )
    assert response.status_code == 409
    assert "managed aircraft bundle" in response.json()["detail"]

    def invalid_merged_layout(request):
        aircraft = planning_payload()["aircraft"]
        aircraft["fuselage"]["length"] = 1
        AircraftSpec.model_validate(aircraft)
        raise AssertionError("Expected complete-layout validation to fail")

    monkeypatch.setattr("openvsp_mcp.fastapi_app.revise_aircraft", invalid_merged_layout)
    response = client.post(
        "/vsp/aircraft/revise",
        json={
            "source_report_path": "/managed/report.json",
            "changes": [{"parameter": "fuselage.length", "value": 1}],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "value_error"
    assert "ctx" not in response.json()["detail"][0]
