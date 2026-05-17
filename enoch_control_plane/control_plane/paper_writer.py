from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
from typing import Any
from urllib import request

from fastapi import HTTPException

from ..config import GateConfig
from ..url_safety import validate_http_url
from .models import PaperRecord


EVIDENCE_TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".csv", ".log", ".py"}
EVIDENCE_PUBLIC_DIR = "evidence"
MAX_EVIDENCE_FILES = 80
MAX_PUBLIC_EVIDENCE_BYTES = 80_000
MAX_METRIC_FILES = 40


def _resolve_project_dir(config: GateConfig, candidate: dict[str, Any]) -> Path:
    project_dir_text = str(candidate.get("project_dir") or "").strip()
    if not project_dir_text:
        raise HTTPException(status_code=400, detail="candidate lacks project_dir")
    root = config.expanded_project_root.resolve()
    project_dir = Path(project_dir_text).expanduser()
    if not project_dir.is_absolute():
        project_dir = root / project_dir
    project_dir = project_dir.resolve()
    try:
        project_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="project_dir escapes configured project root") from exc
    return project_dir


def _write_files(project_dir: Path, files: dict[str, str], *, force: bool) -> None:
    project_dir = project_dir.resolve()
    for rel_path, content in files.items():
        raw_rel_path = str(rel_path or "").strip()
        try:
            target = (project_dir / raw_rel_path).resolve()
            target.relative_to(project_dir)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"paper path escapes project dir: {rel_path}") from exc
        if not raw_rel_path or target == project_dir or (target.exists() and target.is_dir()):
            raise HTTPException(status_code=400, detail=f"paper path is not a file target: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            continue
        target.write_text(content, encoding="utf-8")


def _blocked_empty_claim_ledger(paper: PaperRecord, *, provider_note: Any) -> str:
    return json.dumps({
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
    }, indent=2, sort_keys=True) + "\n"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_evidence_preview(path: Path, *, max_public_bytes: int = MAX_PUBLIC_EVIDENCE_BYTES) -> tuple[str, int, str, bool]:
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
    return preview.decode("utf-8", errors="replace"), total, digest.hexdigest(), total > len(preview)


def _safe_public_evidence_path(rel_path: Path) -> str:
    safe_parts = [re.sub(r"[^A-Za-z0-9._-]+", "_", part).strip("._") or "artifact" for part in rel_path.parts]
    return str(Path(EVIDENCE_PUBLIC_DIR, *safe_parts))


def _iter_source_evidence_files(project_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    explicit = [
        "run_notes.md",
        ".enoch/project_decision.json",
        ".enoch/metrics.json",
        ".enoch/project.json",
        ".enoch/session.json",
        ".enoch/last_message.md",
        ".omx/project_decision.json",
        ".omx/metrics.json",
    ]
    for rel in explicit:
        path = project_dir / rel
        if path.is_file():
            candidates.append(path)
    for rel_dir in ("results", "logs", "scripts", "prompts", ".enoch/logs", ".enoch/state"):
        root = project_dir / rel_dir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.suffix.lower() not in EVIDENCE_TEXT_EXTENSIONS:
                continue
            candidates.append(path)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(project_dir)
        except Exception:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique[:MAX_EVIDENCE_FILES]


def _flatten_json_metrics(value: Any, *, prefix: str = "", out: dict[str, Any] | None = None, limit: int = 120) -> dict[str, Any]:
    if out is None:
        out = {}
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for key, child in value.items():
            if len(out) >= limit:
                break
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_json_metrics(child, prefix=next_prefix, out=out, limit=limit)
    elif isinstance(value, list):
        if value and all(isinstance(item, (int, float, str, bool)) or item is None for item in value[:20]):
            out[prefix or "list"] = value[:20]
        else:
            for idx, child in enumerate(value[:12]):
                if len(out) >= limit:
                    break
                _flatten_json_metrics(child, prefix=f"{prefix}[{idx}]", out=out, limit=limit)
    elif isinstance(value, (int, float, str, bool)) or value is None:
        if prefix:
            out[prefix] = value
    return out


def _metric_summary_for_file(path: Path, rel_path: str, text: str) -> dict[str, Any] | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
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
                return {"source_path": rel_path, "format": "jsonl", "rows_sampled": len(rows), "metrics": _flatten_json_metrics(rows)}
    except Exception as exc:
        return {"source_path": rel_path, "format": suffix.lstrip("."), "parse_error": f"{type(exc).__name__}: {exc}"}
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
    for path in source_files:
        rel_path = str(path.relative_to(project_dir))
        public_content, byte_size, source_sha256, truncated = _read_evidence_preview(path)
        public_path = _safe_public_evidence_path(Path(rel_path))
        entry = {
            "source_path": rel_path,
            "public_path": public_path,
            "bytes": byte_size,
            "sha256": source_sha256,
            "truncated": truncated,
        }
        inventory.append(entry)
        public_files.append({
            "path": public_path,
            "source_path": rel_path,
            "content": public_content,
            "sha256": _sha256_text(public_content),
            "truncated": entry["truncated"],
        })
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
        "source_project_dir": str(candidate.get("source_project_dir") or candidate.get("project_dir") or ""),
        "sync_metadata": candidate.get("evidence_sync") or {},
        "writer_provider": writer_provider,
        "file_inventory": inventory,
        "result_file_refs": result_refs,
        "result_artifacts": result_refs,
        "metric_summaries": metric_summaries,
        "public_evidence_files": public_files,
        "limitations": [] if public_files else ["No source evidence files were available for public evidence packaging."],
    }


def _sentence_claims(markdown: str) -> list[str]:
    body = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    body = re.sub(r"^#+\s+.*$", " ", body, flags=re.M)
    raw_sentences = re.split(r"(?<=[.!?])\s+", body)
    claims: list[str] = []
    signal_re = re.compile(
        r"\b(result|measur|improv|reduce|increase|decrease|pass|fail|accuracy|latency|throughput|speed|token|baseline|evidence|validated|tested|observed|showed|found|negative|positive|support)\b|[0-9]",
        re.I,
    )
    skip_re = re.compile(r"\b(ai provenance|operator claims no|readers should treat|unreviewed ai-generated|no independent human review)\b", re.I)
    for sentence in raw_sentences:
        clean = " ".join(sentence.strip().split())
        clean = clean.strip("-* >")
        if len(clean) < 35 or len(clean) > 360:
            continue
        if skip_re.search(clean):
            continue
        if signal_re.search(clean):
            claims.append(clean)
        if len(claims) >= 16:
            break
    return claims


def _tokenize(value: str) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", value)}


def _claim_evidence_matches(claim: str, public_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claim_tokens = _tokenize(claim)
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in public_files:
        text = str(item.get("content") or "")
        haystack = f"{item.get('source_path')} {text[:20000]}"
        evidence_tokens = _tokenize(haystack)
        if not evidence_tokens:
            continue
        overlap = claim_tokens & evidence_tokens
        score = len(overlap) / max(1, len(claim_tokens))
        if score <= 0:
            continue
        quote = ""
        for line in text.splitlines():
            if len(line.strip()) < 20:
                continue
            if _tokenize(line) & claim_tokens:
                quote = line.strip()[:500]
                break
        scored.append((score, {
            "path": str(item.get("path") or ""),
            "source_path": str(item.get("source_path") or ""),
            "sha256": str(item.get("sha256") or ""),
            "match_score": round(score, 4),
            "quote": quote,
        }))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored:
        return [entry for _, entry in scored[:3]]
    fallback: list[dict[str, Any]] = []
    for item in public_files[:2]:
        fallback.append({
            "path": str(item.get("path") or ""),
            "source_path": str(item.get("source_path") or ""),
            "sha256": str(item.get("sha256") or ""),
            "match_score": 0.0,
            "quote": str(item.get("content") or "").splitlines()[0][:500] if str(item.get("content") or "").splitlines() else "",
            "support_level": "weak_context",
        })
    return fallback


def _build_claim_ledger_data(markdown: str, evidence_bundle: dict[str, Any], paper: PaperRecord, *, writer_provider: Any) -> dict[str, Any]:
    claims = []
    public_files = [item for item in evidence_bundle.get("public_evidence_files") or [] if isinstance(item, dict)]
    for idx, claim in enumerate(_sentence_claims(markdown), start=1):
        refs = _claim_evidence_matches(claim, public_files)
        strong = any(float(ref.get("match_score") or 0) > 0 for ref in refs)
        claims.append({
            "id": f"C{idx}",
            "claim": claim,
            "support_status": "supported" if strong else ("weakly_supported" if refs else "unsupported"),
            "evidence_refs": refs,
            "notes": "Matched by lexical overlap against synced worker artifacts." if strong else ("Linked to synced worker context, but no lexical metric/key match was found." if refs else "No matching synced source artifact found; claim requires manual review."),
        })
    return {
        "schema_version": "claim_ledger.v2",
        "ledger_status": "claims_reference_evidence" if claims and all(item["support_status"] == "supported" for item in claims) else "claims_require_review",
        "paper_id": paper.paper_id,
        "project_id": paper.project_id,
        "run_id": paper.run_id,
        "claims": claims,
        "unsupported_claim_count": sum(1 for item in claims if item["support_status"] == "unsupported"),
        "evidence_bundle_path": paper.evidence_bundle_path,
        "writer_provider": writer_provider,
        "limitations": [] if claims else ["No atomic claims were extracted from the draft."],
    }


def _maybe_preserve_existing_artifact(project_dir: Path, files: dict[str, str], rel_path: str) -> None:
    target = (project_dir / rel_path).resolve()
    try:
        target.relative_to(project_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"paper path escapes project dir: {rel_path}") from exc
    if target.exists() and target.is_file():
        files.pop(rel_path, None)


def deterministic_paper_files(candidate: dict[str, Any], paper: PaperRecord, *, provider_note: str = "deterministic_template_v1") -> dict[str, str]:
    title = str(candidate.get("project_name") or paper.project_id).strip()
    return {
        paper.draft_markdown_path: f"# {title}: Evidence-Grounded Technical Report\n\nStatus: first draft.\n\nGenerated by LangGraph hard-cutover MVP at {paper.generated_at}.\n\n## Automation Status\n\nThis {provider_note} draft proves the new control plane can create paper artifacts. It is intended for automated rewrite/finalization, not operator approval.\n",
        paper.draft_latex_path: "\\documentclass{article}\n\\title{" + title.replace("_", "\\_") + "}\n\\author{Enoch LangGraph MVP}\n\\begin{document}\n\\maketitle\nMVP draft for automated rewrite and finalization.\n\\end{document}\n",
        paper.evidence_bundle_path: json.dumps({"source": "langgraph_control_plane_mvp", "project_id": paper.project_id, "run_id": paper.run_id}, indent=2) + "\n",
        paper.claim_ledger_path: _blocked_empty_claim_ledger(paper, provider_note=provider_note),
        paper.manifest_path: json.dumps({"paper_id": paper.paper_id, "generated_at": paper.generated_at, "writer_provider": provider_note}, indent=2) + "\n",
    }


def _candidate_context(config: GateConfig, candidate: dict[str, Any], paper: PaperRecord) -> str:
    project_dir = _resolve_project_dir(config, candidate)
    snippets: list[str] = []
    seen: set[Path] = set()

    def add_file(rel: str | Path, *, limit: int = 16000) -> None:
        path = (project_dir / rel).resolve()
        try:
            display = path.relative_to(project_dir)
        except ValueError:
            return
        if path in seen or not path.exists() or not path.is_file():
            return
        seen.add(path)
        text = path.read_text(encoding="utf-8", errors="replace")[:limit]
        snippets.append(f"## {display}\n{text}")

    # High-signal project-level evidence. These are copied from the GB10 worker
    # when legacy paper reviews are rewritten on the VM. Do not omit them: the
    # paper writer must not infer “untested” merely because the VM-local
    # publication folder was freshly generated.
    for rel in ("run_notes.md", ".enoch/project_decision.json", ".enoch/metrics.json", ".omx/project_decision.json", ".omx/metrics.json", "logs/main_run.log"):
        add_file(rel, limit=24000)

    # Source paper artifacts from the original research run. These usually carry
    # the claim ledger, evidence strength, tested metrics, and allowed/forbidden
    # wording for publication drafts.
    papers_dir = project_dir / "papers"
    if papers_dir.exists():
        preferred_names = {"evidence_bundle.json", "claim_ledger.json", "paper.md", "paper_manifest.json", "README.md"}
        for path in sorted(papers_dir.rglob("*")):
            if path.is_file() and path.name in preferred_names:
                add_file(path.relative_to(project_dir), limit=22000)

    # Compact result summaries and key JSON outputs. Avoid huge trace CSVs/logs,
    # but include summary CSV/JSON files and top-level result JSONs so the model
    # sees actual measured outcomes.
    results_dir = project_dir / "results"
    if results_dir.exists():
        for path in sorted(results_dir.rglob("*")):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name.endswith(".log") or "trace" in name:
                continue
            if name.endswith("summary.csv") or name.endswith("summary.json") or name in {"hot_cold_sim_results.json", "smoke.json", "hotcold_probe.json"} or ("sweep" in name and name.endswith(".json")):
                add_file(path.relative_to(project_dir), limit=18000)

    return "\n\n".join(snippets) or "No local run artifacts were found; write a cautious review-required draft from the queue metadata only."


def _extract_chat_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices:
        raise ValueError("missing choices in model response")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    raise ValueError("missing text content in model response")


def synthetic_glm_markdown(config: GateConfig, candidate: dict[str, Any], paper: PaperRecord) -> tuple[str, dict[str, Any]]:
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
{json.dumps(candidate, indent=2, sort_keys=True, default=str)}

Paper id: {paper.paper_id}

Local evidence context:
{_candidate_context(config, candidate, paper)}
"""
    payload = {
        "model": config.paper_writer_model,
        "messages": [
            {"role": "system", "content": "You are an expert scientific paper writer and skeptical claim auditor."},
            {"role": "user", "content": prompt},
        ],
        "temperature": config.paper_writer_temperature,
        "max_tokens": config.paper_writer_max_tokens,
    }
    url = validate_http_url(config.paper_writer_base_url.rstrip("/") + "/chat/completions", field_name="paper writer provider url")
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with request.urlopen(req, timeout=config.paper_writer_timeout_sec) as resp:  # noqa: S310 - configured operator provider URL
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    markdown = _extract_chat_content(data)
    return markdown, {"provider": "synthetic.new", "base_url": config.paper_writer_base_url, "model": config.paper_writer_model, "response_id": data.get("id", "")}


def write_paper_artifacts(config: GateConfig, candidate: dict[str, Any], paper: PaperRecord, *, force: bool) -> dict[str, Any]:
    project_dir = _resolve_project_dir(config, candidate)
    provider = config.paper_writer_provider.strip().lower()
    files = deterministic_paper_files(candidate, paper)
    meta: dict[str, Any] = {"provider": "deterministic", "model": "deterministic_template_v1", "fallback_used": False}
    if provider in {"synthetic", "synthetic.new", "synthetic_glm"}:
        try:
            markdown, provider_meta = synthetic_glm_markdown(config, candidate, paper)
            files = deterministic_paper_files(candidate, paper, provider_note="synthetic.new/glm-5.1")
            files[paper.draft_markdown_path] = markdown + "\n"
            files[paper.manifest_path] = json.dumps({"paper_id": paper.paper_id, "generated_at": paper.generated_at, "writer_provider": provider_meta}, indent=2, sort_keys=True) + "\n"
            files[paper.claim_ledger_path] = _blocked_empty_claim_ledger(paper, provider_note=provider_meta)
            # Preserve imported research evidence and claim ledgers. The generated
            # publication draft must not replace real audit artifacts with MVP
            # writer markers, or later rewrites will incorrectly imply that the
            # project has no source evidence or claim/audit state.
            _maybe_preserve_existing_artifact(project_dir, files, paper.evidence_bundle_path)
            _maybe_preserve_existing_artifact(project_dir, files, paper.claim_ledger_path)
            meta = {**provider_meta, "fallback_used": False}
        except Exception as exc:
            if not config.paper_writer_fallback_enabled:
                raise HTTPException(status_code=502, detail=f"paper writer provider failed: {type(exc).__name__}: {exc}") from exc
            meta = {"provider": "deterministic", "model": "deterministic_template_v1", "fallback_used": True, "fallback_reason": f"{type(exc).__name__}: {exc}", "requested_provider": provider}
            files = deterministic_paper_files(candidate, paper, provider_note="deterministic fallback after Synthetic.new/GLM-5.1 failure")
            _maybe_preserve_existing_artifact(project_dir, files, paper.evidence_bundle_path)
            _maybe_preserve_existing_artifact(project_dir, files, paper.claim_ledger_path)
    elif provider not in {"deterministic", "template"}:
        raise HTTPException(status_code=400, detail=f"unsupported paper_writer_provider: {config.paper_writer_provider}")
    if provider in {"deterministic", "template"}:
        pass
    markdown = files.get(paper.draft_markdown_path, "")
    evidence_bundle = _build_evidence_bundle_data(project_dir, candidate, paper, writer_provider=meta)
    if not evidence_bundle.get("public_evidence_files"):
        raise HTTPException(status_code=424, detail={
            "message": "paper artifacts require synced source evidence",
            "project_id": paper.project_id,
            "run_id": paper.run_id,
            "project_dir": str(project_dir),
        })
    claim_ledger = _build_claim_ledger_data(markdown, evidence_bundle, paper, writer_provider=meta)
    files[paper.evidence_bundle_path] = json.dumps(evidence_bundle, indent=2, sort_keys=True) + "\n"
    files[paper.claim_ledger_path] = json.dumps(claim_ledger, indent=2, sort_keys=True) + "\n"
    manifest = json.loads(files.get(paper.manifest_path, "{}") or "{}")
    manifest.update({
        "paper_id": paper.paper_id,
        "generated_at": paper.generated_at,
        "writer_provider": meta,
        "evidence_bundle_path": paper.evidence_bundle_path,
        "claim_ledger_path": paper.claim_ledger_path,
        "evidence_file_count": len(evidence_bundle.get("public_evidence_files") or []),
        "claim_count": len(claim_ledger.get("claims") or []),
        "claim_ledger_status": claim_ledger.get("ledger_status"),
    })
    files[paper.manifest_path] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    _write_files(project_dir, files, force=force)
    return meta


def backfill_paper_evidence_artifacts(
    config: GateConfig,
    candidate: dict[str, Any],
    paper: PaperRecord,
    *,
    force: bool,
    writer_note: str = "evidence_backfill",
) -> dict[str, Any]:
    project_dir = _resolve_project_dir(config, candidate)
    paper_path = (project_dir / paper.draft_markdown_path).resolve()
    try:
        paper_path.relative_to(project_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"paper path escapes project dir: {paper.draft_markdown_path}") from exc
    if not paper_path.exists():
        raise HTTPException(status_code=404, detail=f"paper markdown not found: {paper.draft_markdown_path}")
    markdown = paper_path.read_text(encoding="utf-8", errors="replace")
    provider_meta = {"provider": writer_note, "model": "deterministic_evidence_extractor_v1", "fallback_used": False}
    evidence_bundle = _build_evidence_bundle_data(project_dir, candidate, paper, writer_provider=provider_meta)
    if not evidence_bundle.get("public_evidence_files"):
        raise HTTPException(status_code=424, detail={
            "message": "paper evidence backfill requires synced source evidence",
            "project_id": paper.project_id,
            "run_id": paper.run_id,
            "project_dir": str(project_dir),
        })
    claim_ledger = _build_claim_ledger_data(markdown, evidence_bundle, paper, writer_provider=provider_meta)
    files = {
        paper.evidence_bundle_path: json.dumps(evidence_bundle, indent=2, sort_keys=True) + "\n",
        paper.claim_ledger_path: json.dumps(claim_ledger, indent=2, sort_keys=True) + "\n",
    }
    manifest_path = (project_dir / paper.manifest_path).resolve()
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    manifest.update({
        "paper_id": paper.paper_id,
        "evidence_backfilled": True,
        "evidence_bundle_path": paper.evidence_bundle_path,
        "claim_ledger_path": paper.claim_ledger_path,
        "evidence_file_count": len(evidence_bundle.get("public_evidence_files") or []),
        "claim_count": len(claim_ledger.get("claims") or []),
        "claim_ledger_status": claim_ledger.get("ledger_status"),
    })
    files[paper.manifest_path] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    _write_files(project_dir, files, force=force)
    return {
        **provider_meta,
        "evidence_file_count": len(evidence_bundle.get("public_evidence_files") or []),
        "claim_count": len(claim_ledger.get("claims") or []),
        "claim_ledger_status": claim_ledger.get("ledger_status"),
    }
