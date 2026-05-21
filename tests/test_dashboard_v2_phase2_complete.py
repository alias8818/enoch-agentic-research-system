from pathlib import Path

TODO = Path("docs/dashboard-v2-todo-2026-05-21.md")
REDESIGN = Path("docs/dashboard-redesign-plan.md")
CURSOR = Path("docs/dashboard-v2-cursor-instructions.md")

PHASE2_PR_MARKERS = (
    "#84",
    "#85",
    "#86",
    "#88",
    "#94",
    "#87",
    "#96",
    "#99",
    "#101",
    "#100",
    "#104",
    "#105",
    "#106",
    "#108",
)

PHASE3_DONE_MARKERS = (
    "#109",
    "corpusLinks.ts",
    "SafetyBar.tsx",
    "AutomationPage.tsx",
    "dashboard-v2-cutover-audit.md",
)

CUTOVER = Path("docs/dashboard-v2-cutover-audit.md")

CUTOVER_GATE_RESOLVED = (
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
)

CUTOVER_LANDED_MARKERS = (
    "maintenance_mode: true",
    "AutomationPage.tsx",
    "ResearchPage.tsx",
    "rejectPaper",
    "ListFilterBar",
    "GlobalSearchForm",
    "theme.ts",
    "router.py",
    "no legacy escape hatch",
    "/control/dashboard-v2#",
)


def test_todo_records_phase2_complete_on_main() -> None:
    text = TODO.read_text(encoding="utf-8")
    assert "Phase 2 complete" in text
    assert "Phase 3" in text
    assert "## Phase 2 — command center operator semantics (complete)" in text
    assert "## Phase 3 — optional follow-ups" in text
    for marker in PHASE2_PR_MARKERS:
        assert marker in text


def test_todo_phase2_checklist_fully_checked() -> None:
    text = TODO.read_text(encoding="utf-8")
    phase2_start = text.index("## Phase 2 — command center operator semantics (complete)")
    phase3_start = text.index("## Phase 3 — optional follow-ups")
    phase2_block = text[phase2_start:phase3_start]
    assert "- [ ]" not in phase2_block


def test_redesign_plan_reflects_phase2_complete() -> None:
    text = REDESIGN.read_text(encoding="utf-8")
    assert "Phase 2 complete" in text
    assert "Phase 3" in text
    assert "/control/dashboard-v2" in text


def test_cursor_instructions_phase2_archived_not_reopened() -> None:
    text = CURSOR.read_text(encoding="utf-8")
    assert "Phase 2 (command center semantics + detail route audits) is complete" in text
    assert "## Phase 2 outcomes (merged" in text
    assert "## Archived — Phase 2 Cursor PR sequence (complete)" in text


def test_todo_phase3_records_landed_work_and_open_items() -> None:
    text = TODO.read_text(encoding="utf-8")
    phase3_start = text.index("## Phase 3 — optional follow-ups")
    phase3_block = text[phase3_start:]
    for marker in PHASE3_DONE_MARKERS:
        assert marker in phase3_block
    assert "- [x]" in phase3_block
    assert "- [ ]" in phase3_block
    assert "Workbench KPI noise" in phase3_block
    assert "Cutover audit doc sync" in phase3_block
    assert "One list-page baseline" in phase3_block
    cutover_line = next(line for line in phase3_block.splitlines() if "Cutover audit doc sync" in line)
    assert cutover_line.strip().startswith("- [x]")


def test_cutover_audit_gate_table_reflects_landed_v2() -> None:
    text = CUTOVER.read_text(encoding="utf-8")
    assert "## Cutover gate table (B1–B8)" in text
    assert "Phase 3 re-verification" in text
    for gate_id in CUTOVER_GATE_RESOLVED:
        assert f"| {gate_id} |" in text
    for marker in CUTOVER_LANDED_MARKERS:
        assert marker in text
    assert "**Resolved**" in text
    assert "operator VM check pending" in text or "operator VM step" in text.lower()
    assert "Legacy-only blocker" not in text or "claim review" in text.lower()
    assert "V2 pause omits explicit `maintenance_mode:true`" not in text
    assert "**Legacy-only** — accepted drop for cutover (use API/CLI" not in text
