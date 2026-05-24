#!/usr/bin/env python3
"""Generate and save the OpenAPI schema from the FastAPI application.

Writes docs/openapi.json so the API schema is version-controlled and
available for agents and tools without running the server.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "openapi.json"


def main() -> int:
    # Ensure config stub so FastAPI app can initialize without real config.
    import os

    if not os.environ.get("ENOCH_CONFIG"):
        stub = REPO_ROOT / "config.example.json"
        os.environ["ENOCH_CONFIG"] = str(stub)

    from enoch_control_plane.app import app

    schema = app.openapi()
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"OpenAPI schema written to {SCHEMA_PATH}")
    print(f"  Paths: {len(schema.get('paths', {}))}")
    print(f"  Schemas: {len(schema.get('components', {}).get('schemas', {}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
