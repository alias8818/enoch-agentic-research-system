# Promising Signal Curation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic ranking and bucketed curation to the promising-signals export so the companion repo is useful for research lead discovery.

**Architecture:** Keep system truth in `scripts/export_promising_signals.py`. Ranking is computed from already-exported deterministic fields and persisted into signal records, `data/ranking.json`, manifest summaries, generated ranked indexes, and the public README. Public repo validation recomputes the same deterministic rules from `data/signals.jsonl` and fails on drift.

**Tech Stack:** Python stdlib, pytest, JSON/Markdown generated artifacts, existing Enoch export validation.

---

### Task 1: Deterministic scoring tests

**Files:**
- Modify: `tests/test_export_promising_signals.py`
- Modify: `scripts/export_promising_signals.py`

- [ ] Add tests for `rank_signal()` bucket priority and score explainability.
- [ ] Run the targeted tests and verify they fail because ranking is not implemented.
- [ ] Implement `rank_signal()` and ranking constants from existing signal fields only.
- [ ] Re-run targeted tests and verify they pass.

### Task 2: Export ranking artifacts

**Files:**
- Modify: `tests/test_export_promising_signals.py`
- Modify: `scripts/export_promising_signals.py`

- [ ] Add tests proving `write_export()` writes `data/ranking.json`, `signals/ranked-index.md`, bucket indexes, and manifest `ranking_summary`.
- [ ] Run tests and verify red.
- [ ] Implement ranking artifact generation.
- [ ] Re-run targeted tests and verify green.

### Task 3: Public repo validation and README

**Files:**
- Modify: `../enoch-promising-signals/scripts/validate.py`
- Modify: `../enoch-promising-signals/scripts/validate_public_trust_surfaces.py`
- Generated: `../enoch-promising-signals/README.md`

- [ ] Update public validator to recompute scores/buckets and fail on ranking drift.
- [ ] Ensure README count and ranking links are validated against manifest/current files.
- [ ] Regenerate export and run public validators.

### Task 4: Full verification and release

**Files:**
- Modified generated artifacts in `../enoch-promising-signals`
- Modified source/tests in `enoch-agentic-research-system`

- [ ] Run exporter validation against live rows.
- [ ] Run `uv run pytest -q`, `uv run ruff check .`, and `git diff --check` in the system repo.
- [ ] Run public repo validators.
- [ ] Commit/push both repos if changed.
