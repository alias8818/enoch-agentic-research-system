from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from enoch_control_plane.timeutils import parse_utc_datetime


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"n/a", "never"}:
        return None
    if text.endswith(" UTC"):
        text = text[:-4] + " +0000"
    for fmt in (
        "%a %Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
    ):
        try:
            return datetime.strptime(text, fmt).astimezone(timezone.utc)
        except ValueError:
            pass
    return parse_utc_datetime(text)


def _age_seconds(value: Any, now: datetime) -> int | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0, int((now.astimezone(timezone.utc) - parsed).total_seconds()))


def _latest_timestamp(*values: Any) -> datetime | None:
    parsed = [_parse_timestamp(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    if not parsed:
        return None
    return max(parsed)


def _latest_age_seconds(now: datetime, *values: Any) -> int | None:
    latest = _latest_timestamp(*values)
    if latest is None:
        return None
    return max(0, int((now.astimezone(timezone.utc) - latest).total_seconds()))


def check(
    name: str, ok: bool, detail: str, *, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "data": data or {}}


@dataclass
class _ReadinessAccumulator:
    checks: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def add(self, item: dict[str, Any], blocker: str | None = None) -> None:
        self.checks.append(item)
        if not item["ok"]:
            self.blockers.append(blocker or item["detail"])


def _timer_active(timer: dict[str, Any]) -> bool:
    return str(timer.get("ActiveState") or timer.get("active_state") or "") == "active"


def _service_result(service: dict[str, Any]) -> str:
    return str(service.get("Result") or service.get("result") or "")


def _tick_age_seconds(
    now: datetime, service: dict[str, Any], timer: dict[str, Any]
) -> int | None:
    return _latest_age_seconds(
        now,
        service.get("InactiveEnterTimestamp"),
        service.get("ActiveEnterTimestamp"),
        timer.get("LastTriggerUSec"),
    )


def _worker_lane_metrics(
    worker_lanes: list[Any],
) -> tuple[int, bool, bool]:
    configured_lane_count = sum(
        1
        for lane in worker_lanes
        if not isinstance(lane, dict) or lane.get("configured", True)
    )
    worker_lane_capacity = max(1, configured_lane_count)
    lane_conflict = any(
        isinstance(lane, dict)
        and lane.get("configured", True)
        and int(lane.get("active_count") or 0) > 1
        for lane in worker_lanes
    )
    open_lane_has_queued_work = any(
        isinstance(lane, dict)
        and bool(lane.get("dispatch_available"))
        and int(lane.get("queued_count") or 0) > 0
        for lane in worker_lanes
    )
    return worker_lane_capacity, lane_conflict, open_lane_has_queued_work


def _queued_state_consistent(
    queued: int,
    next_candidate: Any,
    open_lane_has_queued_work: bool,
    active: int,
) -> bool:
    if queued == 0:
        return True
    if bool(next_candidate):
        return True
    if open_lane_has_queued_work:
        return False
    return active > 0


def _add_queue_flag_checks(
    acc: _ReadinessAccumulator, flags: dict[str, Any]
) -> tuple[bool, bool]:
    queue_paused = bool(flags.get("queue_paused"))
    maintenance_mode = bool(flags.get("maintenance_mode"))
    acc.add(
        check(
            "queue_unpaused",
            not queue_paused,
            f"queue_paused={str(queue_paused).lower()}",
            data={"queue_paused": queue_paused},
        ),
        "queue_paused=true",
    )
    acc.add(
        check(
            "maintenance_off",
            not maintenance_mode,
            f"maintenance_mode={str(maintenance_mode).lower()}",
            data={"maintenance_mode": maintenance_mode},
        ),
        "maintenance_mode=true",
    )
    return queue_paused, maintenance_mode


def _add_timer_checks(
    acc: _ReadinessAccumulator, timers: dict[str, dict[str, Any]]
) -> tuple[bool, bool, dict[str, Any], dict[str, Any]]:
    research_timer = timers.get("enoch-research-autopilot.timer") or {}
    corpus_timer = timers.get("enoch-corpus-import-autopilot.timer") or {}
    research_active = _timer_active(research_timer)
    corpus_active = _timer_active(corpus_timer)
    acc.add(
        check(
            "research_timer_active",
            research_active,
            f"research timer active={research_active}",
            data=research_timer,
        ),
        "research timer inactive",
    )
    acc.add(
        check(
            "corpus_timer_active",
            corpus_active,
            f"corpus timer active={corpus_active}",
            data=corpus_timer,
        ),
        "corpus timer inactive",
    )
    return research_active, corpus_active, research_timer, corpus_timer


def _add_service_result_checks(
    acc: _ReadinessAccumulator, services: dict[str, dict[str, Any]]
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    research_service = services.get("enoch-research-autopilot.service") or {}
    corpus_service = services.get("enoch-corpus-import-autopilot.service") or {}
    research_result = _service_result(research_service)
    corpus_result = _service_result(corpus_service)
    acc.add(
        check(
            "research_last_result_success",
            research_result in {"success", ""},
            f"research last result={research_result or 'unknown'}",
            data=research_service,
        ),
        f"research last result={research_result}",
    )
    acc.add(
        check(
            "corpus_last_result_success",
            corpus_result in {"success", ""},
            f"corpus last result={corpus_result or 'unknown'}",
            data=corpus_service,
        ),
        f"corpus last result={corpus_result}",
    )
    return research_result, corpus_result, research_service, corpus_service


def _add_research_tick_check(
    acc: _ReadinessAccumulator,
    *,
    now: datetime,
    research_service: dict[str, Any],
    research_timer: dict[str, Any],
    research_max_age_seconds: int,
) -> int | None:
    research_age = _tick_age_seconds(now, research_service, research_timer)
    research_recent = (
        research_age is not None and research_age <= research_max_age_seconds
    )
    acc.add(
        check(
            "research_tick_recent",
            research_recent,
            f"latest research tick age={research_age if research_age is not None else 'missing'}s max={research_max_age_seconds}s",
            data={
                "age_seconds": research_age,
                "max_age_seconds": research_max_age_seconds,
            },
        ),
        "latest research tick is stale or missing",
    )
    return research_age


def _add_corpus_tick_check(
    acc: _ReadinessAccumulator,
    *,
    now: datetime,
    corpus_service: dict[str, Any],
    corpus_timer: dict[str, Any],
    publish_ready: int,
    corpus_max_age_seconds: int,
) -> int | None:
    corpus_age = _tick_age_seconds(now, corpus_service, corpus_timer)
    corpus_recent = publish_ready == 0 or (
        corpus_age is not None and corpus_age <= corpus_max_age_seconds
    )
    corpus_detail = (
        "publish_ready=0; corpus tick freshness not required"
        if publish_ready == 0
        else f"latest corpus tick age={corpus_age if corpus_age is not None else 'missing'}s max={corpus_max_age_seconds}s"
    )
    acc.add(
        check(
            "corpus_tick_recent_when_needed",
            corpus_recent,
            corpus_detail,
            data={
                "age_seconds": corpus_age,
                "max_age_seconds": corpus_max_age_seconds,
                "publish_ready": publish_ready,
            },
        ),
        f"publish_ready={publish_ready} but latest corpus tick is stale or missing",
    )
    return corpus_age


def _add_blocked_attention_check(
    acc: _ReadinessAccumulator,
    counts: dict[str, Any],
    operator_counts: dict[str, Any],
) -> tuple[int, int]:
    blocked = int(counts.get("blocked") or 0)
    needs_attention = int(operator_counts.get("needs_attention") or 0)
    acc.add(
        check(
            "no_blocked_or_attention",
            blocked == 0 and needs_attention == 0,
            f"blocked={blocked}, needs_attention={needs_attention}",
            data={"blocked": blocked, "needs_attention": needs_attention},
        ),
        "blocked/needs-attention items exist",
    )
    return blocked, needs_attention


def _add_queue_consistency_check(
    acc: _ReadinessAccumulator,
    state: dict[str, Any],
    counts: dict[str, Any],
) -> tuple[int, int]:
    active = int(counts.get("active") or 0)
    queued = int(counts.get("queued") or 0)
    next_candidate = state.get("next_candidate")
    worker_lanes = (
        state.get("worker_lanes") if isinstance(state.get("worker_lanes"), list) else []
    )
    worker_lane_capacity, lane_conflict, open_lane_has_queued_work = (
        _worker_lane_metrics(worker_lanes)
    )
    queued_state_consistent = _queued_state_consistent(
        queued, next_candidate, open_lane_has_queued_work, active
    )
    queue_consistent = (
        active <= worker_lane_capacity and queued_state_consistent and not lane_conflict
    )
    acc.add(
        check(
            "queue_counts_consistent",
            queue_consistent,
            f"queued={queued}, active={active}, next_candidate={bool(next_candidate)}, worker_lane_capacity={worker_lane_capacity}",
            data={
                "queued": queued,
                "active": active,
                "has_next_candidate": bool(next_candidate),
                "worker_lane_capacity": worker_lane_capacity,
                "open_lane_has_queued_work": open_lane_has_queued_work,
                "lane_conflict": lane_conflict,
            },
        ),
        "queued/active state inconsistent",
    )
    return active, queued


def _add_paper_gate_check(acc: _ReadinessAccumulator, pipeline: dict[str, Any]) -> int:
    write_needed = int(pipeline.get("write_needed") or 0)
    raw_candidates = int(pipeline.get("raw_completed_no_paper_candidates") or 0)
    rejected = int(pipeline.get("not_writable_by_decision_gate") or 0)
    gate_consistent = raw_candidates >= write_needed and rejected >= 0
    acc.add(
        check(
            "paper_drafting_positive_gated",
            gate_consistent,
            f"write_needed={write_needed}, raw_candidates={raw_candidates}, decision_gate_rejected={rejected}",
            data={
                "write_needed": write_needed,
                "raw_candidates": raw_candidates,
                "decision_gate_rejected": rejected,
            },
        ),
        "paper drafting gate counters inconsistent",
    )
    return write_needed


def _add_provider_budget_check(
    acc: _ReadinessAccumulator, provider_budget: dict[str, Any] | None
) -> None:
    budget = provider_budget or {"ok": None, "reason": "not checked"}
    budget_ok = budget.get("ok") is True
    acc.add(
        check(
            "provider_budget_ok",
            budget_ok,
            "provider budget ok"
            if budget_ok
            else f"provider budget not ok: {budget.get('failures') or budget.get('reason') or 'unknown'}",
            data=budget,
        ),
        "provider budget below threshold or unavailable",
    )


def _add_research_quality_check(
    acc: _ReadinessAccumulator, research_quality: dict[str, Any] | None
) -> tuple[dict[str, Any], str]:
    quality = research_quality or {
        "ok": False,
        "status": "blocked",
        "problem_counts": {"missing_quality_report": 1},
    }
    quality_status = str(quality.get("status") or "unknown")
    quality_ok = bool(quality.get("ok")) and quality_status in {"clean", "warnings"}
    acc.add(
        check(
            "research_quality_not_blocked",
            quality_ok,
            f"research quality status={quality_status}",
            data=quality,
        ),
        f"research quality status={quality_status}",
    )
    return quality, quality_status


def _add_source_lineage_check(
    acc: _ReadinessAccumulator, source_lineage: dict[str, Any] | None
) -> tuple[dict[str, Any], str]:
    lineage = source_lineage or {
        "ok": False,
        "status": "blocked",
        "problem_counts": {"missing_source_lineage_report": 1},
    }
    lineage_status = str(lineage.get("status") or "unknown")
    lineage_ok = bool(lineage.get("ok")) and lineage_status in {"clean", "warnings"}
    acc.add(
        check(
            "source_lineage_not_blocked",
            lineage_ok,
            f"source lineage status={lineage_status}",
            data=lineage,
        ),
        f"source lineage status={lineage_status}",
    )
    return lineage, lineage_status


def _add_resource_utilization_check(
    acc: _ReadinessAccumulator, resource_utilization: dict[str, Any] | None
) -> tuple[dict[str, Any], bool, int]:
    resource = resource_utilization or {
        "ok": True,
        "status": "clean",
        "finding_count": 0,
        "findings": [],
    }
    resource_ok = bool(resource.get("ok"))
    resource_count = int(
        resource.get("finding_count") or len(resource.get("findings") or [])
    )
    acc.add(
        check(
            "worker_resource_utilization_ok",
            resource_ok,
            f"worker resource utilization findings={resource_count}",
            data=resource,
        ),
        "worker resource policy has active findings",
    )
    return resource, resource_ok, resource_count


def _readiness_research_quality_summary(
    quality: dict[str, Any], quality_status: str
) -> dict[str, Any]:
    return {
        "research_quality_status": quality_status,
        "research_quality_decisions_checked": int(
            quality.get("decisions_checked") or 0
        ),
        "research_quality_problem_counts": quality.get("problem_counts") or {},
        "research_quality_report_path": quality.get("report_path") or "",
        "research_quality_report_mtime": quality.get("report_mtime") or "",
        "research_quality_post_prompt_monitor": quality.get("post_prompt_monitor")
        or {},
    }


def _readiness_source_lineage_summary(
    lineage: dict[str, Any], lineage_status: str
) -> dict[str, Any]:
    return {
        "source_lineage_status": lineage_status,
        "source_lineage_candidates_checked": int(
            lineage.get("candidates_checked") or 0
        ),
        "source_lineage_followups_checked": int(lineage.get("followups_checked") or 0),
        "source_lineage_missing_sources": int(lineage.get("missing_sources") or 0),
        "source_lineage_missing_lineage": int(lineage.get("missing_lineage") or 0),
        "source_lineage_problem_counts": lineage.get("problem_counts") or {},
        "source_lineage_report_path": lineage.get("report_path") or "",
        "source_lineage_report_mtime": lineage.get("report_mtime") or "",
    }


def _readiness_resource_utilization_summary(
    resource: dict[str, Any], resource_ok: bool, resource_count: int
) -> dict[str, Any]:
    return {
        "resource_utilization_status": str(
            resource.get("status") or ("clean" if resource_ok else "blocked")
        ),
        "resource_utilization_findings": resource_count,
    }


@dataclass
class _ReadinessSummaryInput:
    queue_paused: bool
    maintenance_mode: bool
    queued: int
    active: int
    blocked: int
    needs_attention: int
    pipeline: dict[str, Any]
    publish_ready: int
    write_needed: int
    research_active: bool
    research_result: str
    research_age: int | None
    research_max_age_seconds: int
    corpus_active: bool
    corpus_result: str
    corpus_age: int | None
    corpus_max_age_seconds: int
    quality: dict[str, Any]
    quality_status: str
    lineage: dict[str, Any]
    lineage_status: str
    resource: dict[str, Any]
    resource_ok: bool
    resource_count: int


def _build_readiness_summary(inp: _ReadinessSummaryInput) -> dict[str, Any]:
    return {
        "queue_paused": inp.queue_paused,
        "maintenance_mode": inp.maintenance_mode,
        "queued": inp.queued,
        "active": inp.active,
        "blocked": inp.blocked,
        "needs_attention": inp.needs_attention,
        "publish_ready": inp.publish_ready,
        "published_imported": int(inp.pipeline.get("published_imported") or 0),
        "write_needed": inp.write_needed,
        "research_timer_active": inp.research_active,
        "research_last_result": inp.research_result or "unknown",
        "research_tick_age_seconds": inp.research_age,
        "research_tick_max_age_seconds": inp.research_max_age_seconds,
        "corpus_timer_active": inp.corpus_active,
        "corpus_last_result": inp.corpus_result or "unknown",
        "corpus_tick_age_seconds": inp.corpus_age,
        "corpus_tick_max_age_seconds": inp.corpus_max_age_seconds,
        **_readiness_research_quality_summary(inp.quality, inp.quality_status),
        **_readiness_source_lineage_summary(inp.lineage, inp.lineage_status),
        **_readiness_resource_utilization_summary(
            inp.resource, inp.resource_ok, inp.resource_count
        ),
    }


def evaluate_longhaul_readiness(
    *,
    state: dict[str, Any],
    overview: dict[str, Any],
    timers: dict[str, dict[str, Any]],
    services: dict[str, dict[str, Any]],
    provider_budget: dict[str, Any] | None = None,
    research_quality: dict[str, Any] | None = None,
    source_lineage: dict[str, Any] | None = None,
    resource_utilization: dict[str, Any] | None = None,
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
    acc = _ReadinessAccumulator()

    queue_paused, maintenance_mode = _add_queue_flag_checks(acc, flags)
    research_active, corpus_active, research_timer, corpus_timer = _add_timer_checks(
        acc, timers
    )
    research_result, corpus_result, research_service, corpus_service = (
        _add_service_result_checks(acc, services)
    )
    research_age = _add_research_tick_check(
        acc,
        now=now,
        research_service=research_service,
        research_timer=research_timer,
        research_max_age_seconds=research_max_age_seconds,
    )
    publish_ready = int(pipeline.get("publish_ready") or 0)
    corpus_age = _add_corpus_tick_check(
        acc,
        now=now,
        corpus_service=corpus_service,
        corpus_timer=corpus_timer,
        publish_ready=publish_ready,
        corpus_max_age_seconds=corpus_max_age_seconds,
    )
    blocked, needs_attention = _add_blocked_attention_check(
        acc, counts, operator_counts
    )
    active, queued = _add_queue_consistency_check(acc, state, counts)
    write_needed = _add_paper_gate_check(acc, pipeline)
    _add_provider_budget_check(acc, provider_budget)
    quality, quality_status = _add_research_quality_check(acc, research_quality)
    lineage, lineage_status = _add_source_lineage_check(acc, source_lineage)
    resource, resource_ok, resource_count = _add_resource_utilization_check(
        acc, resource_utilization
    )

    status = "ready" if not acc.blockers else "blocked"
    return {
        "ok": not acc.blockers,
        "status": status,
        "label": "Long-haul mode: READY"
        if status == "ready"
        else f"Long-haul mode: BLOCKED — {acc.blockers[0]}",
        "blockers": acc.blockers,
        "checks": acc.checks,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": _build_readiness_summary(
            _ReadinessSummaryInput(
                queue_paused=queue_paused,
                maintenance_mode=maintenance_mode,
                queued=queued,
                active=active,
                blocked=blocked,
                needs_attention=needs_attention,
                pipeline=pipeline,
                publish_ready=publish_ready,
                write_needed=write_needed,
                research_active=research_active,
                research_result=research_result,
                research_age=research_age,
                research_max_age_seconds=research_max_age_seconds,
                corpus_active=corpus_active,
                corpus_result=corpus_result,
                corpus_age=corpus_age,
                corpus_max_age_seconds=corpus_max_age_seconds,
                quality=quality,
                quality_status=quality_status,
                lineage=lineage,
                lineage_status=lineage_status,
                resource=resource,
                resource_ok=resource_ok,
                resource_count=resource_count,
            )
        ),
    }
