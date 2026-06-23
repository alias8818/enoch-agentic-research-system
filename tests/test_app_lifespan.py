from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

import enoch_control_plane.app as appmod


def test_lifespan_shutdown_suppresses_reconcile_task_cancellation(
    monkeypatch: Any,
) -> None:
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


def test_lifespan_restarts_failed_reconcile_task(monkeypatch: Any) -> None:
    calls = 0

    async def fail_once_then_wait() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("reconcile exploded")
        await asyncio.Event().wait()

    async def run_lifespan() -> None:
        monkeypatch.setattr(appmod, "init_sentry", lambda: None)
        monkeypatch.setattr(appmod, "_reconcile_missing_idle_loop", fail_once_then_wait)
        monkeypatch.setattr(appmod, "reconcile_task", None)

        def ignore_exception(_exc: BaseException) -> None:
            return None

        monkeypatch.setattr(appmod, "capture_exception", ignore_exception)

        async with appmod.lifespan(appmod.app):
            for _ in range(10):
                if calls >= 2 and appmod.reconcile_task is not None:
                    break
                await asyncio.sleep(0)
            assert calls >= 2
            assert appmod.reconcile_task is not None
            assert not appmod.reconcile_task.done()

        assert appmod.reconcile_task is None

    asyncio.run(run_lifespan())


def test_readyz_requires_running_reconcile_task(monkeypatch: Any) -> None:
    monkeypatch.setattr(appmod, "reconcile_task", None)

    with pytest.raises(HTTPException) as raised:
        appmod.readyz()

    assert raised.value.status_code == 503
    assert "reconcile task is not running" in str(raised.value.detail)


def test_readyz_reports_state_store_failure(monkeypatch: Any) -> None:
    async def running() -> None:
        await asyncio.Event().wait()

    async def run_check() -> None:
        task = asyncio.create_task(running())
        monkeypatch.setattr(appmod, "reconcile_task", task)

        def list_runs() -> list[Any]:
            raise RuntimeError("state root unavailable")

        monkeypatch.setattr(appmod.store, "list_runs", list_runs)
        try:
            with pytest.raises(HTTPException) as raised:
                appmod.readyz()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        assert raised.value.status_code == 503
        assert "state root unavailable" in str(raised.value.detail)

    asyncio.run(run_check())
    monkeypatch.setattr(appmod, "reconcile_task", None)


def test_healthz_reports_failed_reconcile_task(monkeypatch: Any) -> None:
    async def fail() -> None:
        raise RuntimeError("reconcile dead")

    async def run_check() -> None:
        task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        monkeypatch.setattr(appmod, "reconcile_task", task)

        with pytest.raises(HTTPException) as raised:
            appmod.healthz()

        assert raised.value.status_code == 503
        assert "reconcile dead" in str(raised.value.detail)

    asyncio.run(run_check())
    monkeypatch.setattr(appmod, "reconcile_task", None)


def test_reconcile_loop_continues_after_tick_failure(monkeypatch: Any) -> None:
    calls = 0
    sleeps = 0

    async def flaky_tick() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("tick failed")

    async def bounded_sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError()

    async def run_loop() -> None:
        monkeypatch.setattr(appmod, "_reconcile_missing_idle_once", flaky_tick)
        monkeypatch.setattr(appmod.asyncio, "sleep", bounded_sleep)

        def ignore_exception(_exc: BaseException) -> None:
            return None

        monkeypatch.setattr(appmod, "capture_exception", ignore_exception)

        with pytest.raises(asyncio.CancelledError):
            await appmod._reconcile_missing_idle_loop()

    asyncio.run(run_loop())
    assert calls == 2
