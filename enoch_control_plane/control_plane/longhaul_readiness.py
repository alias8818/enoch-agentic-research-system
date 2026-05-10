from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"n/a", "never"}:
        return None
    if text.endswith(" UTC"):
        text = text[:-4] + " +0000"
    for fmt in ("%a %Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except ValueError:
        return None


def _age_seconds(value: Any, now: datetime) -> int | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0, int((now.astimezone(timezone.utc) - parsed).total_seconds()))


def check(name: str, ok: bool, detail: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "data": data or {}}


def evaluate_longhaul_readiness(
    *,
    state: dict[str, Any],
    overview: dict[str, Any],
    timers: dict[str, dict[str, Any]],
    services: dict[str, dict[str, Any]],
    provider_budget: dict[str, Any] | None = None,
    now: datetime | None = None,
    research_max_age_seconds: int = 2700,
    corpus_max_age_seconds: int = 4500,
) -> dict[str, Any]:
    """Evaluate whether Enoch is in the intended overnight/24x7 posture."""

    now = now or datetime.now(timezone.utc)
    flags = state.get("flags") or {}
    counts = state.get("counts") or {}
    operator_counts = overview.get("operator_counts") or {}
    pipeline = overview.get("paper_pipeline") or {}
    blockers: list[str] = []
    checks: list[dict[str, Any]] = []

    def add(item: dict[str, Any], blocker: str | None = None) -> None:
        checks.append(item)
        if not item["ok"]:
            blockers.append(blocker or item["detail"])

    queue_paused = bool(flags.get("queue_paused"))
    maintenance_mode = bool(flags.get("maintenance_mode"))
    add(check("queue_unpaused", not queue_paused, f"queue_paused={str(queue_paused).lower()}", data={"queue_paused": queue_paused}), "queue_paused=true")
    add(check("maintenance_off", not maintenance_mode, f"maintenance_mode={str(maintenance_mode).lower()}", data={"maintenance_mode": maintenance_mode}), "maintenance_mode=true")

    research_timer = timers.get("enoch-research-autopilot.timer") or {}
    corpus_timer = timers.get("enoch-corpus-import-autopilot.timer") or {}
    research_active = str(research_timer.get("ActiveState") or research_timer.get("active_state") or "") == "active"
    corpus_active = str(corpus_timer.get("ActiveState") or corpus_timer.get("active_state") or "") == "active"
    add(check("research_timer_active", research_active, f"research timer active={research_active}", data=research_timer), "research timer inactive")
    add(check("corpus_timer_active", corpus_active, f"corpus timer active={corpus_active}", data=corpus_timer), "corpus timer inactive")

    research_service = services.get("enoch-research-autopilot.service") or {}
    corpus_service = services.get("enoch-corpus-import-autopilot.service") or {}
    research_result = str(research_service.get("Result") or research_service.get("result") or "")
    corpus_result = str(corpus_service.get("Result") or corpus_service.get("result") or "")
    add(check("research_last_result_success", research_result in {"success", ""}, f"research last result={research_result or 'unknown'}", data=research_service), f"research last result={research_result}")
    add(check("corpus_last_result_success", corpus_result in {"success", ""}, f"corpus last result={corpus_result or 'unknown'}", data=corpus_service), f"corpus last result={corpus_result}")

    research_age = _age_seconds(research_service.get("InactiveEnterTimestamp") or research_timer.get("LastTriggerUSec"), now)
    research_recent = research_age is not None and research_age <= research_max_age_seconds
    add(
        check("research_tick_recent", research_recent, f"latest research tick age={research_age if research_age is not None else 'missing'}s max={research_max_age_seconds}s", data={"age_seconds": research_age, "max_age_seconds": research_max_age_seconds}),
        "latest research tick is stale or missing",
    )

    publish_ready = int(pipeline.get("publish_ready") or 0)
    corpus_age = _age_seconds(corpus_service.get("InactiveEnterTimestamp") or corpus_timer.get("LastTriggerUSec"), now)
    corpus_recent = publish_ready == 0 or (corpus_age is not None and corpus_age <= corpus_max_age_seconds)
    corpus_detail = "publish_ready=0; corpus tick freshness not required" if publish_ready == 0 else f"latest corpus tick age={corpus_age if corpus_age is not None else 'missing'}s max={corpus_max_age_seconds}s"
    add(
        check("corpus_tick_recent_when_needed", corpus_recent, corpus_detail, data={"age_seconds": corpus_age, "max_age_seconds": corpus_max_age_seconds, "publish_ready": publish_ready}),
        f"publish_ready={publish_ready} but latest corpus tick is stale or missing",
    )

    blocked = int(counts.get("blocked") or 0)
    needs_attention = int(operator_counts.get("needs_attention") or 0)
    add(check("no_blocked_or_attention", blocked == 0 and needs_attention == 0, f"blocked={blocked}, needs_attention={needs_attention}", data={"blocked": blocked, "needs_attention": needs_attention}), "blocked/needs-attention items exist")

    active = int(counts.get("active") or 0)
    queued = int(counts.get("queued") or 0)
    next_candidate = state.get("next_candidate")
    queue_consistent = active <= 1 and (queued == 0 or bool(next_candidate) or active > 0)
    add(check("queue_counts_consistent", queue_consistent, f"queued={queued}, active={active}, next_candidate={bool(next_candidate)}", data={"queued": queued, "active": active, "has_next_candidate": bool(next_candidate)}), "queued/active state inconsistent")

    write_needed = int(pipeline.get("write_needed") or 0)
    raw_candidates = int(pipeline.get("raw_completed_no_paper_candidates") or 0)
    rejected = int(pipeline.get("not_writable_by_decision_gate") or 0)
    gate_consistent = raw_candidates >= write_needed and rejected >= 0
    add(check("paper_drafting_positive_gated", gate_consistent, f"write_needed={write_needed}, raw_candidates={raw_candidates}, decision_gate_rejected={rejected}", data={"write_needed": write_needed, "raw_candidates": raw_candidates, "decision_gate_rejected": rejected}), "paper drafting gate counters inconsistent")

    budget = provider_budget or {"ok": None, "reason": "not checked"}
    budget_ok = budget.get("ok") is True
    add(check("provider_budget_ok", budget_ok, "provider budget ok" if budget_ok else f"provider budget not ok: {budget.get('failures') or budget.get('reason') or 'unknown'}", data=budget), "provider budget below threshold or unavailable")

    status = "ready" if not blockers else "blocked"
    return {
        "ok": not blockers,
        "status": status,
        "label": "Long-haul mode: READY" if status == "ready" else f"Long-haul mode: BLOCKED — {blockers[0]}",
        "blockers": blockers,
        "checks": checks,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "queue_paused": queue_paused,
            "maintenance_mode": maintenance_mode,
            "queued": queued,
            "active": active,
            "blocked": blocked,
            "needs_attention": needs_attention,
            "publish_ready": publish_ready,
            "published_imported": int(pipeline.get("published_imported") or 0),
            "write_needed": write_needed,
            "research_timer_active": research_active,
            "research_last_result": research_result or "unknown",
            "research_tick_age_seconds": research_age,
            "research_tick_max_age_seconds": research_max_age_seconds,
            "corpus_timer_active": corpus_active,
            "corpus_last_result": corpus_result or "unknown",
            "corpus_tick_age_seconds": corpus_age,
            "corpus_tick_max_age_seconds": corpus_max_age_seconds,
        },
    }
