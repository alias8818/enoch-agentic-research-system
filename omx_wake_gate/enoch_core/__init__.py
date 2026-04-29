"""Shadow protocol runtime for Enoch/OMX control-plane projections.

Phase 0/1 is intentionally proposal-only: it records local snapshots,
rebuilds derived projections, and proposes candidates without mutating n8n,
Notion, OMX, or paper workflows.
"""

from .models import EnochCoreMode

__all__ = ["EnochCoreMode"]
