#!/usr/bin/env python3
"""Update deterministic public count surfaces from the corpus source of truth."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_public_release import (
    DOC_FILES,
    OWNER_PROFILE_FILES,
    PERSONAL_SITE_FILES,
    PROMISING_COUNT_PHRASES,
    PROFILE_FILES,
    PUBLIC_FILES,
    STRICT_FAIL_PHRASES,
)

DEDUPE_BASELINE = 376


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def existing(root: Path, rels: Iterable[str]) -> list[Path]:
    return [root / rel for rel in rels if (root / rel).exists()]


def fmt_int(value: int) -> str:
    return f"{value:,}"


def require_nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SystemExit(f"{label} must be a non-negative integer")
    return value


def artifact_stats(root: Path) -> dict[str, int]:
    corpus = root / "enoch-ai-research-corpus"
    index = load_json(corpus / "papers" / "index.json")
    quality = load_json(corpus / "quality" / "quality_report.json")
    claim = load_json(corpus / "quality" / "claim_evidence_audit.json")
    artifact_count = require_nonnegative_int(
        index.get("count", len(index.get("papers", []))), label="artifact_count"
    )
    strict_pass = require_nonnegative_int(
        claim.get("strict_claim_evidence_pass_count", 0), label="strict_pass"
    )
    return {
        "artifact_count": artifact_count,
        "packaging_pass": require_nonnegative_int(
            quality.get("passed", artifact_count), label="packaging_pass"
        ),
        "strict_pass": strict_pass,
        "strict_total": require_nonnegative_int(
            claim.get("count", artifact_count), label="strict_total"
        ),
        "strict_fail": artifact_count - strict_pass,
        "empty_claim_ledgers": require_nonnegative_int(
            claim.get("claim_ledgers_empty", claim.get("empty_claim_ledgers", 0)),
            label="empty_claim_ledgers",
        ),
        "result_file_refs": require_nonnegative_int(
            claim.get("result_file_refs", 0), label="result_file_refs"
        ),
        "result_file_refs_missing": require_nonnegative_int(
            claim.get("result_file_refs_missing", 0), label="result_file_refs_missing"
        ),
        "post_dedupe_imports": max(0, artifact_count - DEDUPE_BASELINE),
    }


def generate_manifest(root: Path, output: Path) -> None:
    system = root / "enoch-agentic-research-system"
    committed_path = system / "site" / "ecosystem.json"
    previous = load_json(committed_path) if committed_path.exists() else {}
    subprocess.run(
        [
            sys.executable,
            "scripts/generate_ecosystem_manifest.py",
            "--corpus",
            str(root / "enoch-ai-research-corpus"),
            "--docs",
            str(root / "enoch-docs"),
            "--output",
            str(output),
        ],
        cwd=system,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    generated = load_json(output)
    previous_stable = {k: v for k, v in previous.items() if k != "generated_at"}
    generated_stable = {k: v for k, v in generated.items() if k != "generated_at"}
    if previous and previous_stable == generated_stable:
        generated["generated_at"] = previous.get(
            "generated_at", generated.get("generated_at")
        )
        output.write_text(
            json.dumps(generated, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    committed_path.write_text(output.read_text(encoding="utf-8"), encoding="utf-8")


def update_text(text: str, stats: dict[str, int]) -> str:
    n = stats["artifact_count"]
    p = stats["packaging_pass"]
    sp = stats["strict_pass"]
    sf = stats["strict_fail"]
    promising = stats.get("promising_signal_count", 0)
    empty = stats["empty_claim_ledgers"]
    refs = stats["result_file_refs"]
    missing = stats["result_file_refs_missing"]
    post = stats["post_dedupe_imports"]
    post_count = "one" if post == 1 else str(post)
    post_phrase = f"{post_count} later finalized corpus import" + (
        "" if post == 1 else "s"
    )

    # Meta tags and stat IDs.
    text = re.sub(
        r'(<meta name="enoch-corpus-count" content=")\d+(" />)', rf"\g<1>{n}\2", text
    )
    text = re.sub(
        r'(<meta name="enoch-packaging-provenance-pass-count" content=")\d+(" />)',
        rf"\g<1>{p}\2",
        text,
    )
    text = re.sub(
        r'(<meta name="enoch-strict-claim-evidence-pass-count" content=")\d+(" />)',
        rf"\g<1>{sp}\2",
        text,
    )

    # Count phrases covered by validator plus the launch-announcement wording it intentionally allows.
    # HTML landing pages often split the number and phrase across adjacent tags.
    html_gap = r"(?:\s|<[^>]+>)*"
    count_phrase = re.compile(
        rf"\b\d{{2,5}}\b(?={html_gap}(?:canonical AI-generated artifacts indexed|canonical AI-generated artifacts|canonical AI-generated research artifacts|canonical indexed artifacts|AI-generated artifacts indexed|indexed AI artifacts|AI artifacts|AI-generated research artifacts|generated research artifacts|indexed artifacts|canonical AI-generated papers|canonical papers|canonical artifacts|canonical outputs|artifacts|canonical generated research artifacts))",
        re.I,
    )
    text = count_phrase.sub(str(n), text)
    split_svg_count_phrase = re.compile(
        rf"\b\d{{2,5}}\b(?={html_gap}indexed{html_gap}AI artifacts)", re.I
    )
    text = split_svg_count_phrase.sub(str(n), text)

    packaging_patterns = [
        (
            re.compile(
                rf"\b\d{{2,5}}\s*/\s*\d{{2,5}}(?={html_gap}(?:pass packaging/provenance|pass packaging and provenance|packaging/provenance passed|pass count|quality))",
                re.I,
            ),
            f"{p}/{n}",
        ),
        (
            re.compile(
                r"\b\d{2,5}\s+of\s+\d{2,5}(?=\s+pass(?:es)?\s+(?:the\s+)?packaging(?:/| and )provenance)",
                re.I,
            ),
            f"{p} of {n}",
        ),
        (
            re.compile(
                rf"\b\d{{2,5}}\s*/\s*\d{{2,5}}(?={html_gap}packaging/provenance lint passes)",
                re.I,
            ),
            f"{p}/{n}",
        ),
        (
            re.compile(
                rf"\b\d{{2,5}}\s*/\s*\d{{2,5}}(?={html_gap}pass the packaging/provenance lint)",
                re.I,
            ),
            f"{p}/{n}",
        ),
    ]
    for pattern, replacement in packaging_patterns:
        text = pattern.sub(replacement, text)

    strict_patterns = [
        (
            re.compile(
                rf"\b\d{{1,5}}\s*/\s*\d{{2,5}}(?={html_gap}(?:pass strict claim/evidence|pass strict claim/evidence audit|pass my strict audit gate|strict claim/evidence audit passes|strict claim/evidence audit))",
                re.I,
            ),
            f"{sp}/{n}",
        ),
        (
            re.compile(
                rf"\b\d{{1,5}}\s*/\s*\d{{2,5}}(?={html_gap}pass strict claim and evidence audit)",
                re.I,
            ),
            f"{sp}/{n}",
        ),
        (
            re.compile(
                r"\b\d{1,5}\s*/\s*\d{2,5}(?=; the failure rate is visible)", re.I
            ),
            f"{sp}/{n}",
        ),
        (
            re.compile(
                rf"\b\d{{1,5}}\s*/\s*\d{{2,5}}(?={html_gap}pass the strict claim/evidence audit)",
                re.I,
            ),
            f"{sp}/{n}",
        ),
        (
            re.compile(
                rf"\b\d{{1,5}}\s*/\s*\d{{2,5}}(?={html_gap}pass strict claim/evidence audit)",
                re.I,
            ),
            f"{sp}/{n}",
        ),
        (
            re.compile(
                r"\b\d{1,5}\s*/\s*\d{2,5}(?=\s+pass my strict audit gate)", re.I
            ),
            f"{sp}/{n}",
        ),
        (
            re.compile(r"(?<=Strict audit passes )\d{1,5}\s*/\s*\d{2,5}", re.I),
            f"{sp}/{n}",
        ),
        (
            re.compile(
                r"(?<=Current strict claim/evidence audit status is )\d{1,5}\s*/\s*\d{2,5}",
                re.I,
            ),
            f"{sp}/{n}",
        ),
        (
            re.compile(
                r"(?<=Current status: \*\*)\d{1,5}\s*/\s*\d{2,5}(?= artifacts pass\*\*)",
                re.I,
            ),
            f"{sp} / {n}",
        ),
    ]
    for pattern, replacement in strict_patterns:
        text = pattern.sub(replacement, text)

    strict_prose_patterns = [
        (
            re.compile(
                rf"\b\d{{1,5}}\b(?={html_gap}pass(?:es)?{html_gap}my strict audit)",
                re.I,
            ),
            str(sp),
        ),
        (
            re.compile(
                rf"\b\d{{1,5}}\b(?={html_gap}pass(?:es)?{html_gap}the strict claim/evidence audit)",
                re.I,
            ),
            str(sp),
        ),
        (
            re.compile(
                r"\bstrict (?:claim/evidence )?audit now passes all \d{1,5}\b",
                re.I,
            ),
            lambda _m: f"{_m.group(0).rsplit(' ', 1)[0]} {sp}",
        ),
        (
            re.compile(r"\bstrict pass count to \d{1,5}\b", re.I),
            f"strict pass count to {sp}",
        ),
        (
            re.compile(r"(?<=\")\d{1,5}\s+of\s+\d{2,5}(?=\" is the kind)", re.I),
            f"{sp} of {n}",
        ),
    ]
    for pattern, replacement in strict_prose_patterns:
        text = pattern.sub(replacement, text)

    def replace_strict_fail_counts(match: re.Match[str]) -> str:
        phrase = match.group(0)
        offset = match.start()
        return (
            phrase[: match.start(1) - offset]
            + str(sf)
            + phrase[match.end(1) - offset : match.start(2) - offset]
            + str(n)
            + phrase[match.end(2) - offset :]
        )

    for pattern in STRICT_FAIL_PHRASES:
        text = pattern.sub(replace_strict_fail_counts, text)

    def replace_promising_count(match: re.Match[str]) -> str:
        phrase = match.group(0)
        offset = match.start()
        return (
            phrase[: match.start(1) - offset]
            + str(promising)
            + phrase[match.end(1) - offset :]
        )

    for pattern in PROMISING_COUNT_PHRASES:
        text = pattern.sub(replace_promising_count, text)

    text = re.sub(
        r"\b(?:fails?|rejects)\s+\d{1,5}\s+of\s+them\b",
        lambda m: re.sub(r"\d{1,5}", str(sf), m.group(0), count=1),
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\brejects the other \d{1,5}\b", f"rejects the other {sf}", text, flags=re.I
    )
    text = re.sub(
        r"For \d{1,5} of the \d{2,5} papers", f"For {sf} of the {n} papers", text
    )
    text = re.sub(
        r"\b\d{1,5}\s+empty claim ledgers\b", f"{empty} empty claim ledgers", text
    )
    text = re.sub(
        r"(?<![\d,])\b(?:\d{1,5}|\d{1,3},\d{3})\s+missing public (?:`result_files`|result-file) references\b",
        f"{fmt_int(missing)} missing public result-file references",
        text,
    )
    text = re.sub(
        r"(?<![\d,])\b\d{1,5}\s+result-file references\b",
        f"{fmt_int(refs)} result-file references",
        text,
    )
    text = re.sub(
        r"\b\d{1,5},\d{1,5},\d{3}\s+result-file references\b",
        f"{fmt_int(refs)} result-file references",
        text,
    )
    text = re.sub(
        r"the later corpus import moved the live denominator to \d{2,5}",
        f"{post_phrase} moved the live denominator to {n}",
        text,
    )
    text = re.sub(
        r"\b(?:one|\d+)\s+later finalized corpus imports? moved the live denominator to \d{2,5}",
        f"{post_phrase} moved the live denominator to {n}",
        text,
    )
    text = re.sub(
        r"\d{2,5} unique topics from the duplicate-cleanup pass plus \w+ later finalized corpus imports?",
        f"{DEDUPE_BASELINE} unique topics from the duplicate-cleanup pass plus {post_phrase}",
        text,
    )
    return text


def default_generated_manifest_path() -> Path:
    fd, path = tempfile.mkstemp(
        prefix="enoch-ecosystem.generated.",
        suffix=".json",
    )
    os.close(fd)
    return Path(path)


def public_files(root: Path) -> list[Path]:
    return (
        existing(root / "enoch-agentic-research-system", PUBLIC_FILES)
        + existing(root / "alias8818.github.io", PROFILE_FILES)
        + existing(root / "enoch-docs", DOC_FILES)
        + existing(root / "alias8818", OWNER_PROFILE_FILES)
        + existing(root / "jeremyblankenship.dev", PERSONAL_SITE_FILES)
        + existing(
            root / "enoch-ai-research-corpus",
            [
                "README.md",
                "quality/quality_report.md",
                "quality/packaging_provenance_report.md",
            ],
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--generated-manifest",
        type=Path,
        default=None,
        help=(
            "Staging path for a freshly generated ecosystem manifest; "
            "defaults to a private mkstemp file under the system temp directory"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    stats = artifact_stats(root)
    if stats["strict_total"] != stats["artifact_count"]:
        raise SystemExit(
            f"strict total {stats['strict_total']} != artifact count {stats['artifact_count']}"
        )
    if not args.dry_run:
        generated_manifest = args.generated_manifest
        if generated_manifest is None:
            generated_manifest = default_generated_manifest_path()
        generate_manifest(root, generated_manifest)
        stats["promising_signal_count"] = require_nonnegative_int(
            load_json(generated_manifest).get("promising_signal_count", 0),
            label="promising_signal_count",
        )
    changed: list[str] = []
    for path in public_files(root):
        old = path.read_text(encoding="utf-8", errors="replace")
        new = update_text(old, stats)
        if new != old:
            changed.append(str(path.relative_to(root)))
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "dry_run": bool(args.dry_run),
                "stats": stats,
                "changed": changed,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
