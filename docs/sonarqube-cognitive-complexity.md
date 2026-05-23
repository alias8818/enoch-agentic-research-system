# SonarQube cognitive complexity policy (S3776)

**Date:** 2026-05-23
**Project key:** `alias8818_enoch-agentic-research-system_6ab334f2-c45e-42db-87ce-a99310229989`
**Rules:** `python:S3776`, `typescript:S3776` — *Cognitive Complexity of functions should not be too high*

## Why 15 for production

This repository is mostly Python control-plane, queue, dispatch, state, evidence, and dashboard logic. High branch nesting in those surfaces is where regressions hide. **15 per function/method** is the production default; **25 would be too permissive** for the control-plane core.

SonarSource recommends enforcing cognitive complexity at the **method/function rule** (`S3776`), **not** as a project-wide “total cognitive complexity” quality-gate condition (that metric scales with repository size).

## Thresholds by scope

| Scope | Threshold | Enforcement |
| ----- | ---------: | ----------- |
| Python / TypeScript app code (`enoch_control_plane`, `dashboard/src` non-test) | **15** | Active `S3776` (SonarWay default + SonarLint `threshold: 15`) |
| Tests (`tests/**`, `*.test.ts`, `dashboard/e2e/**`) | **20–25** (guideline) | Rule stays **15** on scan; use **Won’t Fix** only when complexity is mostly scenario setup or table-driven fixtures |
| Scripts / deploy utilities (`scripts/**`, `deploy/**`) | **20** (guideline) | Prefer refactor; accept up to ~20 only for CLI parsing / migration glue |
| Generated / vendor / build output | Exclude | `sonar.exclusions`, `dashboard_v2/**`, `artifacts/**`, etc. |
| C/C++ (if added later) | **25** | Reserve for native extensions |

## Practical gate (human + CI)

| Situation | Action |
| --------- | ------ |
| New production code **> 15** | **Fail** — extract helpers / named phases before merge |
| Legacy production **16–24** | **Warn** — schedule refactor; do not raise the global threshold |
| Any function **≥ 25** | **Block** unless there is a documented, reviewed exception |
| Any function **≥ 30** | **Refactor** — usually hidden state-machine logic |

Quality gate: use **Sonar way** (or equivalent) on **new code** issues; do **not** add a condition on total cognitive complexity.

## Configuration in this repo

| Surface | Location |
| ------- | -------- |
| Scanner scope / exclusions | `sonar-project.properties` |
| IDE threshold override | `.vscode/settings.json` → `sonarlint.rules` |
| Deterministic checks | `tests/test_sonar_configuration.py` |

Rule parameters are owned by the **Quality Profile** on the SonarQube server (SonarWay uses threshold **15**). Per-project overrides belong in a **child profile** for this project only—not in `sonar-project.properties` (Sonar does not read rule parameters there).

## Fixing violations

1. `ReadLints` / SonarLint on the file.
2. `show_rule` for `python:S3776` or `typescript:S3776`.
3. Extract branches into named helpers; keep orchestrators linear.
4. `analyze_code_snippet` with `scope: TEST` for test files.
5. Run targeted pytest / dashboard tests when behavior changes.

See also `.cursor/skills/sonarqube-workflow/SKILL.md`.
