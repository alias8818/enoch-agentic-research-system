from __future__ import annotations

import json
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib import request

from fastapi import HTTPException

from ..config import GateConfig
from ..url_safety import validate_http_url
from .models import PaperRecord


JSON_FILE_SUFFIX = ".json"
EVIDENCE_TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    JSON_FILE_SUFFIX,
    ".jsonl",
    ".csv",
    ".log",
    ".py",
}
EVIDENCE_PUBLIC_DIR = "evidence"
PAPER_PATH_LABEL = "paper path"
MAX_EVIDENCE_FILES = 80
MAX_PUBLIC_EVIDENCE_BYTES = 80_000
MAX_METRIC_FILES = 40
MAX_SECRET_TOKEN_LENGTH = 12_000
SECRET_REDACTION_PATTERNS = [
    re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)([A-Za-z0-9._\-]{16,})"),
    re.compile(
        r"(?i)((?:OPENAI|ANTHROPIC|SYNTHETIC|GITHUB|HF|HUGGINGFACE|SUPABASE)[_-](?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*)([^\s'\"]{12,})"
    ),
    re.compile(r"(?i)((?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*)([^\s'\"]{12,})"),
    re.compile(r"\b(sk-(?:proj-)?[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b(syn_[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{20,})\b"),
]


def _redact_public_evidence_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_REDACTION_PATTERNS:

        def repl(match: re.Match[str]) -> str:
            if match.lastindex and match.lastindex >= 2:
                prefix = match.group(1)
                token = match.group(2)
                if len(token) > MAX_SECRET_TOKEN_LENGTH:
                    return match.group(0)
                return f"{prefix}[REDACTED_TOKEN]"
            token = match.group(1)
            if len(token) > MAX_SECRET_TOKEN_LENGTH:
                return match.group(0)
            return "[REDACTED_TOKEN]"

        redacted = pattern.sub(repl, redacted)
    return redacted


def _redact_metadata(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_public_evidence_text(value)
    if isinstance(value, list):
        return [_redact_metadata(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_metadata(child) for key, child in value.items()}
    return value


def _resolve_project_dir(config: GateConfig, candidate: dict[str, Any]) -> Path:
    project_dir_text = str(candidate.get("project_dir") or "").strip()
    if not project_dir_text:
        raise HTTPException(status_code=400, detail="candidate lacks project_dir")
    try:
        root = config.expanded_project_root.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="configured project root could not be resolved"
        ) from exc
    try:
        project_dir = Path(project_dir_text).expanduser()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400, detail="project_dir contains an unexpandable user home"
        ) from exc
    if not project_dir.is_absolute():
        project_dir = root / project_dir
    try:
        project_dir = project_dir.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="project_dir could not be resolved"
        ) from exc
    try:
        project_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="project_dir escapes configured project root"
        ) from exc
    return project_dir


def _resolved_project_dir_for_write(project_dir: Path) -> Path:
    try:
        return project_dir.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="project_dir could not be resolved"
        ) from exc


def _paper_write_target(project_dir: Path, rel_path: Any) -> tuple[Path, str]:
    raw_rel_path = str(rel_path or "").strip()
    try:
        target = (project_dir / raw_rel_path).resolve()
        target.relative_to(project_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"paper path escapes project dir: {rel_path}"
        ) from exc
    return target, raw_rel_path


def _paper_path_not_file_target_detail(rel_path: Any) -> str:
    return f"paper path is not a file target: {rel_path}"


def _reject_directory_or_empty_paper_target(
    target: Path, project_dir: Path, rel_path: Any, raw_rel_path: str
) -> None:
    if not raw_rel_path or target == project_dir:
        raise HTTPException(
            status_code=400, detail=_paper_path_not_file_target_detail(rel_path)
        )
    if _path_exists_for_paper(
        target, label=PAPER_PATH_LABEL
    ) and _path_is_dir_for_paper(target, label=PAPER_PATH_LABEL):
        raise HTTPException(
            status_code=400, detail=_paper_path_not_file_target_detail(rel_path)
        )


def _atomic_write_text_file(target: Path, content: str) -> None:
    tmp_path = target.with_name(f".{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, target)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _write_single_paper_file(
    project_dir: Path, rel_path: Any, content: str, *, force: bool
) -> None:
    target, raw_rel_path = _paper_write_target(project_dir, rel_path)
    _reject_directory_or_empty_paper_target(target, project_dir, rel_path, raw_rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _path_exists_for_paper(target, label=PAPER_PATH_LABEL) and not force:
        return
    _atomic_write_text_file(target, content)


def _write_files(project_dir: Path, files: dict[str, str], *, force: bool) -> None:
    project_dir = _resolved_project_dir_for_write(project_dir)
    for rel_path, content in files.items():
        _write_single_paper_file(project_dir, rel_path, content, force=force)


def _blocked_empty_claim_ledger(paper: PaperRecord, *, provider_note: Any) -> str:
    return (
        json.dumps(
            {
                "schema_version": "claim_ledger.v1",
                "paper_id": paper.paper_id,
                "project_id": paper.project_id,
                "run_id": paper.run_id,
                "audit_status": "blocked_empty_claims",
                "claims": [],
                "limitations": [
                    "No structured claims were extracted for this artifact.",
                    "This artifact must not pass strict claim/evidence audit until claims reference public evidence files.",
                ],
                "writer_provider": provider_note,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_evidence_preview(
    path: Path, *, max_public_bytes: int = MAX_PUBLIC_EVIDENCE_BYTES
) -> tuple[str, int, str, bool]:
    digest = hashlib.sha256()
    preview = bytearray()
    total = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
            if len(preview) < max_public_bytes:
                remaining = max_public_bytes - len(preview)
                preview.extend(chunk[:remaining])
    public_text = _redact_public_evidence_text(
        preview.decode("utf-8", errors="replace")
    )
    return public_text, total, digest.hexdigest(), total > len(preview)


def _path_exists_for_paper(path: Path, *, label: str, status_code: int = 400) -> bool:
    try:
        return path.exists()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status_code, detail=f"{label} could not be inspected: {path}"
        ) from exc


def _path_is_file_for_paper(path: Path, *, label: str, status_code: int = 400) -> bool:
    try:
        return path.is_file()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status_code, detail=f"{label} could not be inspected: {path}"
        ) from exc


def _path_is_dir_for_paper(path: Path, *, label: str, status_code: int = 400) -> bool:
    try:
        return path.is_dir()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status_code, detail=f"{label} could not be inspected: {path}"
        ) from exc


def _path_exists_quiet(path: Path) -> bool:
    try:
        return path.exists()
    except (OSError, RuntimeError, ValueError):
        return False


def _path_is_file_quiet(path: Path) -> bool:
    try:
        return path.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def _safe_public_evidence_path(rel_path: Path) -> str:
    safe_parts = [
        re.sub(r"[^A-Za-z0-9._-]+", "_", part).strip("._") or "artifact"
        for part in rel_path.parts
    ]
    return str(Path(EVIDENCE_PUBLIC_DIR, *safe_parts))


def _dedupe_public_evidence_path(
    public_path: str, used_paths: set[str], source_sha256: str
) -> str:
    if public_path not in used_paths:
        used_paths.add(public_path)
        return public_path
    raw = Path(public_path)
    stem = raw.stem or "artifact"
    suffix = raw.suffix
    digest = (source_sha256 or _sha256_text(public_path))[:12]
    for index in range(1, 1000):
        candidate = str(raw.with_name(f"{stem}-{digest}-{index}{suffix}"))
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
    raise HTTPException(
        status_code=500,
        detail=f"could not allocate unique public evidence path for {public_path}",
    )


_EXPLICIT_SOURCE_EVIDENCE_RELS = (
    "run_notes.md",
    ".enoch/project_decision.json",
    ".enoch/metrics.json",
    ".omx/project_decision.json",
    ".omx/metrics.json",
)


def _collect_explicit_source_evidence(project_dir: Path) -> list[Path]:
    found: list[Path] = []
    for rel in _EXPLICIT_SOURCE_EVIDENCE_RELS:
        path = project_dir / rel
        if _path_exists_for_paper(
            path, label="source evidence path", status_code=424
        ) and _path_is_file_for_paper(
            path, label="source evidence path", status_code=424
        ):
            found.append(path)
    return found


def _is_scannable_source_evidence_file(path: Path) -> bool:
    if "__pycache__" in path.parts or path.suffix == ".pyc":
        return False
    return path.suffix.lower() in EVIDENCE_TEXT_EXTENSIONS


def _scan_source_evidence_directory(project_dir: Path, rel_dir: str) -> list[Path]:
    root = project_dir / rel_dir
    if not _path_exists_for_paper(
        root, label="source evidence directory", status_code=424
    ):
        return []
    if not _path_is_dir_for_paper(
        root, label="source evidence directory", status_code=424
    ):
        return []
    try:
        paths = sorted(root.rglob("*"))
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=424,
            detail=f"source evidence directory could not be scanned: {rel_dir}",
        ) from exc
    found: list[Path] = []
    for path in paths:
        if not _path_is_file_for_paper(
            path, label="source evidence file", status_code=424
        ):
            continue
        if not _is_scannable_source_evidence_file(path):
            continue
        found.append(path)
    return found


def _dedupe_resolved_source_evidence(
    candidates: list[Path], project_dir: Path
) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(project_dir)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=424,
                detail="source evidence file path could not be resolved",
            ) from exc
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique[:MAX_EVIDENCE_FILES]


def _iter_source_evidence_files(project_dir: Path) -> list[Path]:
    """Collect unique evidence files for the paper writer."""
    candidates = _collect_explicit_source_evidence(project_dir)
    candidates.extend(_scan_source_evidence_directory(project_dir, "results"))
    return _dedupe_resolved_source_evidence(candidates, project_dir)


def _metrics_at_limit(out: dict[str, Any], limit: int) -> bool:
    return len(out) >= limit


def _is_scalar_metric_value(value: Any) -> bool:
    return isinstance(value, (int, float, str, bool)) or value is None


def _is_simple_primitive_list(value: list[Any]) -> bool:
    return bool(value) and all(
        isinstance(item, (int, float, str, bool)) or item is None for item in value[:20]
    )


def _flatten_dict_metrics(
    value: dict[Any, Any],
    *,
    prefix: str,
    out: dict[str, Any],
    limit: int,
) -> None:
    for key, child in value.items():
        if _metrics_at_limit(out, limit):
            break
        next_prefix = f"{prefix}.{key}" if prefix else str(key)
        _flatten_json_metrics(child, prefix=next_prefix, out=out, limit=limit)


def _flatten_list_metrics(
    value: list[Any],
    *,
    prefix: str,
    out: dict[str, Any],
    limit: int,
) -> None:
    if _is_simple_primitive_list(value):
        out[prefix or "list"] = value[:20]
        return
    for idx, child in enumerate(value[:12]):
        if _metrics_at_limit(out, limit):
            break
        _flatten_json_metrics(child, prefix=f"{prefix}[{idx}]", out=out, limit=limit)


def _flatten_scalar_metric(
    value: Any,
    *,
    prefix: str,
    out: dict[str, Any],
) -> None:
    if prefix:
        out[prefix] = value


def _flatten_json_metrics(
    value: Any, *, prefix: str = "", out: dict[str, Any] | None = None, limit: int = 120
) -> dict[str, Any]:
    if out is None:
        out = {}
    if _metrics_at_limit(out, limit):
        return out
    if isinstance(value, dict):
        _flatten_dict_metrics(value, prefix=prefix, out=out, limit=limit)
    elif isinstance(value, list):
        _flatten_list_metrics(value, prefix=prefix, out=out, limit=limit)
    elif _is_scalar_metric_value(value):
        _flatten_scalar_metric(value, prefix=prefix, out=out)
    return out


def _metric_summary_for_file(
    path: Path, rel_path: str, text: str
) -> dict[str, Any] | None:
    suffix = path.suffix.lower()
    try:
        if suffix == JSON_FILE_SUFFIX:
            data = json.loads(text)
            metrics = _flatten_json_metrics(data)
            return {"source_path": rel_path, "format": "json", "metrics": metrics}
        if suffix == ".jsonl":
            rows = []
            for line in text.splitlines()[:50]:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
            if rows:
                return {
                    "source_path": rel_path,
                    "format": "jsonl",
                    "rows_sampled": len(rows),
                    "metrics": _flatten_json_metrics(rows),
                }
    except Exception as exc:
        return {
            "source_path": rel_path,
            "format": suffix.lstrip("."),
            "parse_error": f"{type(exc).__name__}: {exc}",
        }
    return None


def _build_evidence_bundle_data(
    project_dir: Path,
    candidate: dict[str, Any],
    paper: PaperRecord,
    *,
    writer_provider: Any,
) -> dict[str, Any]:
    source_files = _iter_source_evidence_files(project_dir)
    inventory: list[dict[str, Any]] = []
    public_files: list[dict[str, Any]] = []
    metric_summaries: list[dict[str, Any]] = []
    used_public_paths: set[str] = set()
    for path in source_files:
        rel_path = str(path.relative_to(project_dir))
        try:
            public_content, byte_size, source_sha256, truncated = (
                _read_evidence_preview(path)
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=424,
                detail={
                    "message": "source evidence file could not be read",
                    "source_path": rel_path,
                    "project_id": paper.project_id,
                    "run_id": paper.run_id,
                },
            ) from exc
        public_path = _dedupe_public_evidence_path(
            _safe_public_evidence_path(Path(rel_path)), used_public_paths, source_sha256
        )
        entry = {
            "source_path": rel_path,
            "public_path": public_path,
            "bytes": byte_size,
            "sha256": source_sha256,
            "truncated": truncated,
        }
        inventory.append(entry)
        public_files.append(
            {
                "path": public_path,
                "source_path": rel_path,
                "content": public_content,
                "sha256": _sha256_text(public_content),
                "truncated": entry["truncated"],
            }
        )
        if len(metric_summaries) < MAX_METRIC_FILES:
            summary = _metric_summary_for_file(path, rel_path, public_content)
            if summary is not None:
                metric_summaries.append(summary)
    result_refs = [item["path"] for item in public_files]
    return {
        "schema_version": "evidence_bundle.v2",
        "source": "enoch_control_plane",
        "paper_id": paper.paper_id,
        "project_id": paper.project_id,
        "run_id": paper.run_id,
        "source_run_id": str(candidate.get("run_id") or paper.run_id or ""),
        "source_project_dir": str(
            candidate.get("source_project_dir") or candidate.get("project_dir") or ""
        ),
        "sync_metadata": _redact_metadata(candidate.get("evidence_sync") or {}),
        "writer_provider": _redact_metadata(writer_provider),
        "file_inventory": inventory,
        "result_file_refs": result_refs,
        "result_artifacts": result_refs,
        "metric_summaries": metric_summaries,
        "public_evidence_files": public_files,
        "limitations": []
        if public_files
        else ["No source evidence files were available for public evidence packaging."],
    }


def _markdown_body_without_fences_and_headers(markdown: str) -> str:
    """Drop fenced code blocks and ATX headings without backtracking-prone regex."""
    kept: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _sentence_claims(markdown: str) -> list[str]:
    """Extract candidate claim sentences from markdown.

    Uses safe (non-regex-backtracking) detection for signal keywords to avoid ReDoS.
    """
    body = _markdown_body_without_fences_and_headers(markdown)
    raw_sentences = re.split(r"(?<=[.!?])\s+", body)
    claims: list[str] = []

    # Safe keyword-based signal detection (avoids catastrophic backtracking in the
    # previous long alternation regex that Sonar flagged as ReDoS risk).
    SIGNAL_KEYWORDS = (
        "result",
        "measur",
        "improv",
        "reduce",
        "increase",
        "decrease",
        "pass",
        "fail",
        "accuracy",
        "latency",
        "throughput",
        "speed",
        "token",
        "baseline",
        "evidence",
        "validated",
        "tested",
        "observed",
        "showed",
        "found",
        "negative",
        "positive",
        "support",
    )

    SKIP_KEYWORDS = (
        "ai provenance",
        "operator claims no",
        "readers should treat",
        "unreviewed ai-generated",
        "no independent human review",
    )

    for sentence in raw_sentences:
        clean = " ".join(sentence.strip().split())
        clean = clean.strip("-* >")
        if len(clean) < 35 or len(clean) > 360:
            continue

        lower = clean.lower()
        if any(kw in lower for kw in SKIP_KEYWORDS):
            continue

        if any(kw in lower for kw in SIGNAL_KEYWORDS) or any(
            ch.isdigit() for ch in clean
        ):
            claims.append(clean)

        if len(claims) >= 16:
            break
    return claims


def _tokenize(value: str) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", value)}


def _first_matching_quote(text: str, claim_tokens: set[str]) -> str:
    for line in text.splitlines():
        if len(line.strip()) < 20:
            continue
        if _tokenize(line) & claim_tokens:
            return line.strip()[:500]
    return ""


def _claim_token_overlap_score(
    claim_tokens: set[str], evidence_tokens: set[str]
) -> float:
    if not evidence_tokens:
        return 0.0
    overlap = claim_tokens & evidence_tokens
    return len(overlap) / max(1, len(claim_tokens))


def _evidence_ref_dict(
    item: dict[str, Any],
    *,
    match_score: float,
    quote: str,
    support_level: str | None = None,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "path": str(item.get("path") or ""),
        "source_path": str(item.get("source_path") or ""),
        "sha256": str(item.get("sha256") or ""),
        "match_score": round(match_score, 4) if match_score > 0 else 0.0,
        "quote": quote,
    }
    if support_level is not None:
        ref["support_level"] = support_level
    return ref


def _score_public_file_match(
    claim_tokens: set[str], item: dict[str, Any]
) -> tuple[float, str] | None:
    text = str(item.get("content") or "")
    haystack = f"{item.get('source_path')} {text[:20000]}"
    score = _claim_token_overlap_score(claim_tokens, _tokenize(haystack))
    if score <= 0:
        return None
    return score, _first_matching_quote(text, claim_tokens)


def _weak_context_evidence_fallback(
    public_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fallback: list[dict[str, Any]] = []
    for item in public_files[:2]:
        content = str(item.get("content") or "")
        lines = content.splitlines()
        quote = lines[0][:500] if lines else ""
        fallback.append(
            _evidence_ref_dict(
                item,
                match_score=0.0,
                quote=quote,
                support_level="weak_context",
            )
        )
    return fallback


def _claim_evidence_matches(
    claim: str, public_files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    claim_tokens = _tokenize(claim)
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in public_files:
        match = _score_public_file_match(claim_tokens, item)
        if match is None:
            continue
        score, quote = match
        scored.append((score, _evidence_ref_dict(item, match_score=score, quote=quote)))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored:
        return [entry for _, entry in scored[:3]]
    return _weak_context_evidence_fallback(public_files)


def _claim_support_metadata(
    strong: bool, refs: list[dict[str, Any]]
) -> tuple[str, str]:
    if strong:
        return (
            "supported",
            "Matched by lexical overlap against synced worker artifacts.",
        )
    if refs:
        return (
            "weakly_supported",
            "Linked to synced worker context, but no lexical metric/key match was found.",
        )
    return (
        "unsupported",
        "No matching synced source artifact found; claim requires manual review.",
    )


def _build_claim_ledger_data(
    markdown: str,
    evidence_bundle: dict[str, Any],
    paper: PaperRecord,
    *,
    writer_provider: Any,
) -> dict[str, Any]:
    claims = []
    public_files = [
        item
        for item in evidence_bundle.get("public_evidence_files") or []
        if isinstance(item, dict)
    ]
    for idx, claim in enumerate(_sentence_claims(markdown), start=1):
        refs = _claim_evidence_matches(claim, public_files)
        strong = any(float(ref.get("match_score") or 0) > 0 for ref in refs)
        support_status, notes = _claim_support_metadata(strong, refs)
        claims.append(
            {
                "id": f"C{idx}",
                "claim": claim,
                "support_status": support_status,
                "evidence_refs": refs,
                "notes": notes,
            }
        )
    all_supported = claims and all(
        item["support_status"] == "supported" for item in claims
    )
    return {
        "schema_version": "claim_ledger.v2",
        "ledger_status": "claims_reference_evidence"
        if all_supported
        else "claims_require_review",
        "paper_id": paper.paper_id,
        "project_id": paper.project_id,
        "run_id": paper.run_id,
        "claims": claims,
        "unsupported_claim_count": sum(
            1 for item in claims if item["support_status"] == "unsupported"
        ),
        "evidence_bundle_path": paper.evidence_bundle_path,
        "writer_provider": _redact_metadata(writer_provider),
        "limitations": []
        if claims
        else ["No atomic claims were extracted from the draft."],
    }


def _maybe_preserve_existing_artifact(
    project_dir: Path, files: dict[str, str], rel_path: str
) -> None:
    try:
        target = (project_dir / rel_path).resolve()
        target.relative_to(project_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"paper path escapes project dir: {rel_path}"
        ) from exc
    artifact_name = Path(rel_path).name
    if artifact_name.startswith("evidence"):
        label = "paper evidence artifact"
    elif "claim" in artifact_name:
        label = "paper claim artifact"
    else:
        label = "paper artifact"
    if _path_exists_for_paper(target, label=label) and _path_is_file_for_paper(
        target, label=label
    ):
        files.pop(rel_path, None)


def deterministic_paper_files(
    candidate: dict[str, Any],
    paper: PaperRecord,
    *,
    provider_note: str = "deterministic_template_v1",
) -> dict[str, str]:
    title = str(candidate.get("project_name") or paper.project_id).strip()
    return {
        paper.draft_markdown_path: f"# {title}: Evidence-Grounded Technical Report\n\nStatus: first draft.\n\nGenerated by LangGraph hard-cutover MVP at {paper.generated_at}.\n\n## Automation Status\n\nThis {provider_note} draft proves the new control plane can create paper artifacts. It is intended for automated rewrite/finalization, not operator approval.\n",
        paper.draft_latex_path: "\\documentclass{article}\n\\title{"
        + title.replace("_", "\\_")
        + "}\n\\author{Enoch LangGraph MVP}\n\\begin{document}\n\\maketitle\nMVP draft for automated rewrite and finalization.\n\\end{document}\n",
        paper.evidence_bundle_path: json.dumps(
            {
                "source": "langgraph_control_plane_mvp",
                "project_id": paper.project_id,
                "run_id": paper.run_id,
            },
            indent=2,
        )
        + "\n",
        paper.claim_ledger_path: _blocked_empty_claim_ledger(
            paper, provider_note=provider_note
        ),
        paper.manifest_path: json.dumps(
            {
                "paper_id": paper.paper_id,
                "generated_at": paper.generated_at,
                "writer_provider": provider_note,
            },
            indent=2,
        )
        + "\n",
    }


_PROJECT_LEVEL_EVIDENCE_RELS = (
    "run_notes.md",
    ".enoch/project_decision.json",
    ".enoch/metrics.json",
    ".omx/project_decision.json",
    ".omx/metrics.json",
    "logs/main_run.log",
)
_PREFERRED_PAPER_ARTIFACT_NAMES = frozenset(
    {
        "evidence_bundle.json",
        "claim_ledger.json",
        "paper.md",
        "paper_manifest.json",
        "README.md",
    }
)
_RESULT_SUMMARY_JSON_NAMES = frozenset(
    {"hot_cold_sim_results.json", "smoke.json", "hotcold_probe.json"}
)


def _try_append_context_snippet(
    project_dir: Path,
    rel: str | Path,
    *,
    seen: set[Path],
    snippets: list[str],
    limit: int = 16000,
) -> None:
    path = (project_dir / rel).resolve()
    try:
        display = path.relative_to(project_dir)
    except ValueError:
        return
    if path in seen or not _path_exists_quiet(path) or not _path_is_file_quiet(path):
        return
    seen.add(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, RuntimeError, ValueError):
        return
    snippets.append(f"## {display}\n{_redact_public_evidence_text(text)}")


def _append_project_level_evidence(
    project_dir: Path, *, seen: set[Path], snippets: list[str]
) -> None:
    for rel in _PROJECT_LEVEL_EVIDENCE_RELS:
        _try_append_context_snippet(
            project_dir, rel, seen=seen, snippets=snippets, limit=24000
        )


def _append_paper_artifacts(
    project_dir: Path, *, seen: set[Path], snippets: list[str]
) -> None:
    papers_dir = project_dir / "papers"
    if not _path_exists_quiet(papers_dir):
        return
    try:
        for p in sorted(papers_dir.rglob("*")):
            if _path_is_file_quiet(p) and p.name in _PREFERRED_PAPER_ARTIFACT_NAMES:
                _try_append_context_snippet(
                    project_dir,
                    p.relative_to(project_dir),
                    seen=seen,
                    snippets=snippets,
                    limit=22000,
                )
    except (OSError, RuntimeError, ValueError):
        pass


def _is_result_summary_candidate(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".log") or "trace" in name:
        return False
    if name.endswith(("summary.csv", "summary.json")):
        return True
    if name in _RESULT_SUMMARY_JSON_NAMES:
        return True
    return "sweep" in name and name.endswith(JSON_FILE_SUFFIX)


def _append_result_summaries(
    project_dir: Path, *, seen: set[Path], snippets: list[str]
) -> None:
    results_dir = project_dir / "results"
    if not _path_exists_quiet(results_dir):
        return
    try:
        for p in sorted(results_dir.rglob("*")):
            if not _path_is_file_quiet(p) or not _is_result_summary_candidate(p):
                continue
            _try_append_context_snippet(
                project_dir,
                p.relative_to(project_dir),
                seen=seen,
                snippets=snippets,
                limit=18000,
            )
    except (OSError, RuntimeError, ValueError):
        pass


def _candidate_context(
    config: GateConfig, candidate: dict[str, Any], paper: PaperRecord
) -> str:
    """Gather compact, high-signal local evidence for the paper writer."""
    project_dir = _resolve_project_dir(config, candidate)
    snippets: list[str] = []
    seen: set[Path] = set()
    _append_project_level_evidence(project_dir, seen=seen, snippets=snippets)
    _append_paper_artifacts(project_dir, seen=seen, snippets=snippets)
    _append_result_summaries(project_dir, seen=seen, snippets=snippets)
    return (
        "\n\n".join(snippets)
        or "No local run artifacts were found; write a cautious review-required draft from the queue metadata only."
    )


def _text_from_content_part(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    text = item.get("text") or item.get("content")
    return text.strip() if isinstance(text, str) else None


def _text_from_message_content(content: Any) -> str | None:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return None
    parts = [part for item in content if (part := _text_from_content_part(item))]
    return "\n".join(parts).strip() if parts else None


def _extract_chat_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices:
        raise ValueError("missing choices in model response")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    text = _text_from_message_content(content)
    if text:
        return text
    raise ValueError("missing text content in model response")


def synthetic_glm_markdown(
    config: GateConfig, candidate: dict[str, Any], paper: PaperRecord
) -> tuple[str, dict[str, Any]]:
    api_key = config.paper_writer_api_key or os.environ.get("SYNTHETIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("Synthetic.new API key is not configured")
    title = str(candidate.get("project_name") or paper.project_id).strip()
    prompt = f"""Write a publication-quality technical paper draft in Markdown for this research result.

Requirements:
- Use a precise academic tone without hype.
- Preserve uncertainty and negative/mixed results honestly.
- Include sections: Abstract, Introduction, Method, Results, Limitations, Reproducibility Checklist, Conclusion.
- Do not invent citations, metrics, hardware results, or claims not supported by the context.
- If the context contains run notes, evidence bundles, claim ledgers, benchmark results, or decision JSON, treat those as empirical/prototype evidence and summarize them accurately. Do NOT say no experiments, no implementation, or no empirical results when those artifacts are present.
- Distinguish carefully between toy simulation results, llama.cpp hook-prototype results, CUDA copy calibration, and final production validation.
- Never write TODO, FIXME, placeholder citations, or "citation needed". If external citation details are not present in the context, omit external references rather than inserting placeholders. Prefer a "Referenced artifacts" section that names the local run notes, evidence bundle, claim ledger, metrics, source files, and result files actually present in the context.
- Keep the draft reviewable and evidence-grounded.
- Include a clear AI provenance / no-human-credit note near the top: this draft was AI-generated from automated research artifacts, the operator claims no personal authorship credit for the writing or results beyond releasing the artifact, and readers should treat it as an unreviewed AI-generated research artifact. Do not require a human reviewer in the note, and do not use the phrase "No human reviewer has validated".

Project metadata:
{_redact_public_evidence_text(json.dumps(candidate, indent=2, sort_keys=True, default=str))}

Paper id: {paper.paper_id}

Local evidence context:
{_candidate_context(config, candidate, paper)}
"""
    payload = {
        "model": config.paper_writer_model,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert scientific paper writer and skeptical claim auditor.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": config.paper_writer_temperature,
        "max_tokens": config.paper_writer_max_tokens,
    }
    url = validate_http_url(
        config.paper_writer_base_url.rstrip("/") + "/chat/completions",
        field_name="paper writer provider url",
    )
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with request.urlopen(req, timeout=config.paper_writer_timeout_sec) as resp:  # noqa: S310 - configured operator provider URL
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    markdown = _extract_chat_content(data)
    return markdown, {
        "provider": "synthetic.new",
        "base_url": config.paper_writer_base_url,
        "model": config.paper_writer_model,
        "response_id": data.get("id", ""),
    }


def write_paper_artifacts(
    config: GateConfig, candidate: dict[str, Any], paper: PaperRecord, *, force: bool
) -> dict[str, Any]:
    project_dir = _resolve_project_dir(config, candidate)
    provider = config.paper_writer_provider.strip().lower()
    files = deterministic_paper_files(candidate, paper)
    meta: dict[str, Any] = {
        "provider": "deterministic",
        "model": "deterministic_template_v1",
        "fallback_used": False,
    }
    if provider in {"synthetic", "synthetic.new", "synthetic_glm"}:
        try:
            markdown, provider_meta = synthetic_glm_markdown(config, candidate, paper)
            files = deterministic_paper_files(
                candidate, paper, provider_note="synthetic.new/glm-5.1"
            )
            files[paper.draft_markdown_path] = markdown + "\n"
            files[paper.manifest_path] = (
                json.dumps(
                    {
                        "paper_id": paper.paper_id,
                        "generated_at": paper.generated_at,
                        "writer_provider": provider_meta,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            files[paper.claim_ledger_path] = _blocked_empty_claim_ledger(
                paper, provider_note=provider_meta
            )
            # Preserve imported research evidence and claim ledgers. The generated
            # publication draft must not replace real audit artifacts with MVP
            # writer markers, or later rewrites will incorrectly imply that the
            # project has no source evidence or claim/audit state.
            _maybe_preserve_existing_artifact(
                project_dir, files, paper.evidence_bundle_path
            )
            _maybe_preserve_existing_artifact(
                project_dir, files, paper.claim_ledger_path
            )
            meta = {**provider_meta, "fallback_used": False}
        except HTTPException:
            raise
        except Exception as exc:
            if not config.paper_writer_fallback_enabled:
                raise HTTPException(
                    status_code=502,
                    detail=f"paper writer provider failed: {type(exc).__name__}: {exc}",
                ) from exc
            meta = {
                "provider": "deterministic",
                "model": "deterministic_template_v1",
                "fallback_used": True,
                "fallback_reason": f"{type(exc).__name__}: {exc}",
                "requested_provider": provider,
            }
            files = deterministic_paper_files(
                candidate,
                paper,
                provider_note="deterministic fallback after Synthetic.new/GLM-5.1 failure",
            )
            _maybe_preserve_existing_artifact(
                project_dir, files, paper.evidence_bundle_path
            )
            _maybe_preserve_existing_artifact(
                project_dir, files, paper.claim_ledger_path
            )
    elif provider not in {"deterministic", "template"}:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported paper_writer_provider: {config.paper_writer_provider}",
        )
    markdown = files.get(paper.draft_markdown_path, "")
    evidence_bundle = _build_evidence_bundle_data(
        project_dir, candidate, paper, writer_provider=meta
    )
    if not evidence_bundle.get("public_evidence_files"):
        raise HTTPException(
            status_code=424,
            detail={
                "message": "paper artifacts require synced source evidence",
                "project_id": paper.project_id,
                "run_id": paper.run_id,
                "project_dir": str(project_dir),
            },
        )
    claim_ledger = _build_claim_ledger_data(
        markdown, evidence_bundle, paper, writer_provider=meta
    )
    files[paper.evidence_bundle_path] = (
        json.dumps(evidence_bundle, indent=2, sort_keys=True) + "\n"
    )
    files[paper.claim_ledger_path] = (
        json.dumps(claim_ledger, indent=2, sort_keys=True) + "\n"
    )
    manifest = json.loads(files.get(paper.manifest_path, "{}") or "{}")
    manifest.update(
        {
            "paper_id": paper.paper_id,
            "generated_at": paper.generated_at,
            "writer_provider": meta,
            "evidence_bundle_path": paper.evidence_bundle_path,
            "claim_ledger_path": paper.claim_ledger_path,
            "evidence_file_count": len(
                evidence_bundle.get("public_evidence_files") or []
            ),
            "claim_count": len(claim_ledger.get("claims") or []),
            "claim_ledger_status": claim_ledger.get("ledger_status"),
        }
    )
    files[paper.manifest_path] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    _write_files(project_dir, files, force=force)
    return meta


def _read_paper_markdown_for_backfill(project_dir: Path, paper: PaperRecord) -> str:
    try:
        paper_path = (project_dir / paper.draft_markdown_path).resolve()
        paper_path.relative_to(project_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"paper path escapes project dir: {paper.draft_markdown_path}",
        ) from exc
    if not _path_exists_for_paper(paper_path, label="paper markdown"):
        raise HTTPException(
            status_code=404,
            detail=f"paper markdown not found: {paper.draft_markdown_path}",
        )
    try:
        return paper_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"paper markdown could not be read: {paper.draft_markdown_path}",
        ) from exc


def _load_paper_manifest_for_backfill(
    project_dir: Path, paper: PaperRecord
) -> dict[str, Any]:
    manifest: dict[str, Any] = {}
    try:
        manifest_path = (project_dir / paper.manifest_path).resolve()
        manifest_path.relative_to(project_dir)
        if _path_exists_for_paper(manifest_path, label="paper manifest"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {}
            except (OSError, RuntimeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"paper manifest could not be read: {paper.manifest_path}",
                ) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"paper path escapes project dir: {paper.manifest_path}",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        manifest = {}
    return manifest


def backfill_paper_evidence_artifacts(
    config: GateConfig,
    candidate: dict[str, Any],
    paper: PaperRecord,
    *,
    force: bool,
    writer_note: str = "evidence_backfill",
) -> dict[str, Any]:
    project_dir = _resolve_project_dir(config, candidate)
    markdown = _read_paper_markdown_for_backfill(project_dir, paper)
    provider_meta = {
        "provider": writer_note,
        "model": "deterministic_evidence_extractor_v1",
        "fallback_used": False,
    }
    evidence_bundle = _build_evidence_bundle_data(
        project_dir, candidate, paper, writer_provider=provider_meta
    )
    if not evidence_bundle.get("public_evidence_files"):
        raise HTTPException(
            status_code=424,
            detail={
                "message": "paper evidence backfill requires synced source evidence",
                "project_id": paper.project_id,
                "run_id": paper.run_id,
                "project_dir": str(project_dir),
            },
        )
    claim_ledger = _build_claim_ledger_data(
        markdown, evidence_bundle, paper, writer_provider=provider_meta
    )
    files = {
        paper.evidence_bundle_path: json.dumps(
            evidence_bundle, indent=2, sort_keys=True
        )
        + "\n",
        paper.claim_ledger_path: json.dumps(claim_ledger, indent=2, sort_keys=True)
        + "\n",
    }
    manifest = _load_paper_manifest_for_backfill(project_dir, paper)
    manifest.update(
        {
            "paper_id": paper.paper_id,
            "evidence_backfilled": True,
            "evidence_bundle_path": paper.evidence_bundle_path,
            "claim_ledger_path": paper.claim_ledger_path,
            "evidence_file_count": len(
                evidence_bundle.get("public_evidence_files") or []
            ),
            "claim_count": len(claim_ledger.get("claims") or []),
            "claim_ledger_status": claim_ledger.get("ledger_status"),
        }
    )
    files[paper.manifest_path] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    _write_files(project_dir, files, force=force)
    return {
        **provider_meta,
        "evidence_file_count": len(evidence_bundle.get("public_evidence_files") or []),
        "claim_count": len(claim_ledger.get("claims") or []),
        "claim_ledger_status": claim_ledger.get("ledger_status"),
    }
