from __future__ import annotations

import asyncio

import enoch_control_plane.app as appmod


def test_lifespan_shutdown_suppresses_reconcile_task_cancellation(monkeypatch) -> None:
    async def never_finishes() -> None:
        await asyncio.Event().wait()

    async def run_lifespan() -> None:
        monkeypatch.setattr(appmod, "init_sentry", lambda: None)
        monkeypatch.setattr(appmod, "_reconcile_missing_idle_loop", never_finishes)
        monkeypatch.setattr(appmod, "reconcile_task", None)

        async with appmod.lifespan(appmod.app):
            assert appmod.reconcile_task is not None
            assert not appmod.reconcile_task.done()

        assert appmod.reconcile_task is None

    asyncio.run(run_lifespan())
