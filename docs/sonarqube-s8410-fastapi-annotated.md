# SonarQube S8410 — FastAPI `Annotated` dependency inventory

**Date:** 2026-05-23
**Project key:** `alias8818_enoch-agentic-research-system_6ab334f2-c45e-42db-87ce-a99310229989`

## Rule summary

| Field | Value |
|-------|-------|
| **Rule key** | `python:S8410` |
| **Name** | FastAPI dependencies should use "Annotated" type hints |
| **Severity** | BLOCKER |
| **Type** | CODE_SMELL |
| **Impact** | MAINTAINABILITY (BLOCKER) |

FastAPI route parameters must not use `Depends()`, `Query()`, `Path()`, `Body()`, or `Header()` as **default values**. Move injection metadata into `Annotated[Type, ...]` and keep real defaults as ordinary `= value` when needed.

### Fix patterns

```python
# Header (auth)
authorization: Annotated[str | None, Header()] = None

# Query
refresh_worker: Annotated[bool, Query()] = False
page_size: Annotated[int, Query(ge=1, le=200)] = 50

# Body
payload: Annotated[dict[str, Any] | None, Body()] = None
```

Requires `from typing import Annotated` (already available on Python 3.9+).

## Open issue count

| Rule | Severity | Count |
|------|----------|------:|
| `python:S8410` | BLOCKER | **139** |

### By file

| File | Issues |
|------|-------:|
| `enoch_control_plane/control_plane/router.py` | 108 |
| `enoch_control_plane/app.py` | 23 |
| `enoch_control_plane/enoch_core/router.py` | 8 |

### By injection type (codebase grep + Sonar alignment)

| Pattern | Approx. count |
|---------|--------------:|
| `Header(default=...)` | 87 |
| `Query(default=...)` | 48 |
| `Body(default=...)` | 4 |
| `Depends(...)` | 0 |

No `Depends()` usages found; violations are almost entirely legacy `Header` / `Query` / `Body` default syntax.

## Example fixes applied (proof only)

Two mechanical fixes in `router.py` (count >> 10, full migration deferred):

1. **`dashboard_status`** — `refresh_worker` Query + `authorization` Header
2. **`dashboard_preflight`** — `authorization` Header (Sonar issue `2ef6f714-a69d-443c-a2cc-77c08440a792`, line 8236)

Remaining **137** issues need the same pattern applied file-wide (likely a scripted codemod or dedicated PR).

## Reference

- [FastAPI — Annotated dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/#use-annotated-in-fastapi)
- Sonar rule: `python:S8410`
