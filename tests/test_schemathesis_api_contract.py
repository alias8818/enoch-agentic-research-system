from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from hypothesis import given, settings
import schemathesis

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import create_control_plane_router


TOKEN = "schemathesis-token"


def _config(tmp_path: Path) -> GateConfig:
    return GateConfig(
        state_dir=str(tmp_path / "state"),
        project_root=str(tmp_path / "projects"),
        dispatch_script_path=str(tmp_path / "dispatch.sh"),
        control_api_bearer_token=TOKEN,
        completion_callback_url="http://callback",
        completion_callback_token="callback",
    )


def _app(tmp_path: Path) -> FastAPI:
    app = FastAPI()

    def require_bearer(authorization: str | None) -> None:
        if authorization != f"Bearer {TOKEN}":
            raise HTTPException(status_code=401, detail="unauthorized")

    app.include_router(create_control_plane_router(_config(tmp_path), require_bearer))
    return app


def test_schemathesis_read_only_health_contract(tmp_path: Path) -> None:
    schema = schemathesis.openapi.from_asgi("/openapi.json", _app(tmp_path))
    operation = schema["/control/health"]["get"]

    @settings(max_examples=5, deadline=None)
    @given(case=operation.as_strategy())
    def run_case(case) -> None:  # noqa: ANN001 - schemathesis supplies the case object
        case.call_and_validate(headers={"Authorization": f"Bearer {TOKEN}"})

    run_case()
