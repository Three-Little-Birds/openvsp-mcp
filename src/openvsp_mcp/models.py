"""Typed request/response models for OpenVSP MCP calls."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VSPCommand(BaseModel):
    """Single OpenVSP script command."""

    command: str = Field(..., description="Literal line inserted into the VSP script")


class OpenVSPRequest(BaseModel):
    """Parameters controlling geometry edits and optional VSPAero run."""

    geometry_file: str = Field(..., description="Path to the .vsp3 file")
    set_commands: list[VSPCommand] = Field(default_factory=list, description="Commands to run")
    run_vspaero: bool = Field(True, description="Execute VSPAero after editing geometry")
    case_name: str = Field("case", description="Base name for generated results")


class OpenVSPResponse(BaseModel):
    """Response object capturing generated paths."""

    script_path: str = Field(..., description="Absolute path to the temporary script file")
    result_path: str | None = Field(
        None,
        description="Path to the generated VSPAero .adb file (if run_vspaero=True)",
    )
