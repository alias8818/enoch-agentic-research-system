from __future__ import annotations

import json
from typing import Any


def canonical_json(payload: Any) -> str:
    """Canonical JSON used for payload hashing across all Enoch stores."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
