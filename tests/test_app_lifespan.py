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


def test_lifespan_shutdown_closes_telemetry_collector(monkeypatch: Any) -> None:
    closed = False

    async def never_finishes() -> None:
        await asyncio.Event().wait()

    class FakeTelemetry:
        def close(self) -> None:
            nonlocal closed
            closed = True

    async def run_lifespan() -> None:
        monkeypatch.setattr(appmod, "init_sentry", lambda: None)
        monkeypatch.setattr(appmod, "_reconcile_missing_idle_loop", never_finishes)
        monkeypatch.setattr(appmod, "reconcile_task", None)
        monkeypatch.setattr(appmod, "telemetry", FakeTelemetry())

        async with appmod.lifespan(appmod.app):
            assert closed is False

        assert closed is True
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

        def check_runs_dir_readable() -> None:
            raise RuntimeError("state root unavailable")

        monkeypatch.setattr(
            appmod.store, "check_runs_dir_readable", check_runs_dir_readable
        )
        try:
            with pytest.raises(HTTPException) as raised:
                appmod.readyz()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        detail = str(raised.value.detail)
        assert raised.value.status_code == 503
        assert "state store unavailable" in detail
        assert "state root unavailable" not in detail

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

        detail = str(raised.value.detail)
        assert raised.value.status_code == 503
        assert "reconcile task failed" in detail
        assert "reconcile dead" not in detail

    asyncio.run(run_check())
    monkeypatch.setattr(appmod, "reconcile_task", None)


def test_readyz_does_not_expose_exception_details(monkeypatch: Any) -> None:
    async def fail_with_sensitive_detail() -> None:
        raise RuntimeError("Bearer secret-token leaked stack detail")

    async def run_check() -> None:
        task = asyncio.create_task(fail_with_sensitive_detail())
        await asyncio.sleep(0)
        monkeypatch.setattr(appmod, "reconcile_task", task)

        def check_runs_dir_readable() -> None:
            raise RuntimeError("database password=supersecret")

        monkeypatch.setattr(
            appmod.store, "check_runs_dir_readable", check_runs_dir_readable
        )

        with pytest.raises(HTTPException) as raised:
            appmod.readyz()

        detail = str(raised.value.detail)
        assert raised.value.status_code == 503
        assert "reconcile task failed" in detail
        assert "state store unavailable" in detail
        assert "secret-token" not in detail
        assert "password=supersecret" not in detail

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
