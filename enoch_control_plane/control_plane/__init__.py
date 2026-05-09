"""Canonical LangGraph-ready Enoch control plane.

This package is the hard-cutover replacement surface for the former n8n-owned
queue/controller/paper automations.  The MVP intentionally starts with a
portable SQLite-backed state store and typed FastAPI routes so it can run on a
separate VM while the GB10 remains a worker lane.
"""

from .router import create_control_plane_router
from .store import ControlPlaneStore

__all__ = ["ControlPlaneStore", "create_control_plane_router"]
