"""Factory for the OpenVSP FastAPI surface."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .core import OPENVSP_BIN, VSPAERO_BIN, execute_openvsp
from .describe import describe_geometry
from .models import (
    OpenVSPGeometryRequest,
    OpenVSPInspectResponse,
    OpenVSPRequest,
    OpenVSPResponse,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenVSP MCP Service",
        version="0.2.0",
        description="Inspect and automate OpenVSP geometry edits, with optional VSPAero runs.",
    )

    @app.post("/vsp/inspect", response_model=OpenVSPInspectResponse)
    def inspect(request: OpenVSPGeometryRequest) -> OpenVSPInspectResponse:
        try:
            return describe_geometry(request.geometry_file)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/vsp/modify", response_model=OpenVSPResponse)
    def modify(request: OpenVSPRequest) -> OpenVSPResponse:
        try:
            return execute_openvsp(request.model_copy(update={"run_vspaero": False}))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/vsp/run", response_model=OpenVSPResponse)
    def run_vspaero(request: OpenVSPRequest) -> OpenVSPResponse:
        try:
            return execute_openvsp(request.model_copy(update={"run_vspaero": True}))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "vsp": OPENVSP_BIN, "vspaero": VSPAERO_BIN}

    return app


app = create_app()

__all__ = ["create_app", "app"]
