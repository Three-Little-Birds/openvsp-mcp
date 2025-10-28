"""Factory for the OpenVSP FastAPI surface."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .core import OPENVSP_BIN, VSPAERO_BIN, execute_openvsp
from .models import OpenVSPRequest, OpenVSPResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenVSP MCP Service",
        version="0.1.0",
        description="Automate OpenVSP edits and optional VSPAero runs.",
    )

    @app.post("/vsp", response_model=OpenVSPResponse)
    def run_openvsp(request: OpenVSPRequest) -> OpenVSPResponse:
        try:
            return execute_openvsp(request)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "vsp": OPENVSP_BIN, "vspaero": VSPAERO_BIN}

    return app


app = create_app()

__all__ = ["create_app", "app"]
