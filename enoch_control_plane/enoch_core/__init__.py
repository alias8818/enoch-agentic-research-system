"""Control-plane projection helpers for Enoch runtime ledgers.

This package does not mutate legacy workflow tools, Notion, or paper workflows.
Event and snapshot payload hashes are computed from the shared canonical JSON
format in :mod:`enoch_control_plane.enoch_core._canonical`: sorted keys, compact
separators, UTF-8 text preserved with ``ensure_ascii=False``. Both SQLite and
Supabase stores must use that exact format so cutovers and replays preserve
idempotency semantics.
"""
