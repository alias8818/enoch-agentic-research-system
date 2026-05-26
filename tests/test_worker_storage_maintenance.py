from pathlib import Path

from scripts.worker_storage_maintenance import (
    build_report,
    discover_candidates,
    human_bytes,
)


def test_discovers_recreatable_dirs_but_skips_artifacts(tmp_path: Path) -> None:
    project = tmp_path / "project-a"
    (project / ".venv" / "lib").mkdir(parents=True)
    (project / ".venv" / "lib" / "payload.bin").write_bytes(b"x" * 7)
    (project / "src" / "__pycache__").mkdir(parents=True)
    (project / "src" / "__pycache__" / "mod.pyc").write_bytes(b"x" * 3)
    (project / "artifacts" / "model.bin").mkdir(parents=True)
    (project / "artifacts" / "model.bin" / "weights").write_bytes(b"x" * 11)

    candidates = discover_candidates(tmp_path)
    paths = {item.path.relative_to(tmp_path).as_posix(): item for item in candidates}

    assert "project-a/.venv" in paths
    assert "project-a/src/__pycache__" in paths
    assert all("artifacts" not in path for path in paths)
    assert sum(item.size_bytes for item in candidates) >= 10


def test_reserved_name_project_directory_is_not_cleanup_candidate(
    tmp_path: Path,
) -> None:
    reserved_project = tmp_path / ".venv"
    (reserved_project / "evidence").mkdir(parents=True)
    (reserved_project / "evidence" / "proof.txt").write_text(
        "valuable evidence\n", encoding="utf-8"
    )
    (reserved_project / "artifacts").mkdir()
    (reserved_project / "artifacts" / "output.bin").write_bytes(b"x" * 3)
    (reserved_project / "src" / "__pycache__").mkdir(parents=True)
    (reserved_project / "src" / "__pycache__" / "mod.pyc").write_bytes(b"x")

    candidates = discover_candidates(tmp_path)
    paths = {item.path.relative_to(tmp_path).as_posix() for item in candidates}

    assert ".venv" not in paths
    assert ".venv/evidence" not in paths
    assert ".venv/artifacts" not in paths
    assert ".venv/src/__pycache__" in paths


def test_protects_named_projects(tmp_path: Path) -> None:
    (tmp_path / "queued-project" / ".venv").mkdir(parents=True)
    (tmp_path / "queued-project" / ".venv" / "payload.bin").write_bytes(b"x")

    [candidate] = discover_candidates(tmp_path, protected_projects={"queued-project"})

    assert candidate.protected is True
    assert "queued-project" in candidate.protect_reason


def test_candidate_dirs_are_pruned_to_prevent_nested_double_count(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project-a"
    (project / ".venv" / "lib" / "pkg" / "__pycache__").mkdir(parents=True)
    (project / ".venv" / "lib" / "pkg" / "__pycache__" / "mod.pyc").write_bytes(
        b"x" * 13
    )

    candidates = discover_candidates(tmp_path)
    paths = [item.path.relative_to(tmp_path).as_posix() for item in candidates]

    assert paths == ["project-a/.venv"]
    assert candidates[0].size_bytes >= 13


def test_report_uses_unique_bytes_for_hardlinked_candidates(tmp_path: Path) -> None:
    project_a = tmp_path / "project-a" / ".venv"
    project_b = tmp_path / "project-b" / ".venv"
    project_a.mkdir(parents=True)
    project_b.mkdir(parents=True)
    source = project_a / "shared.bin"
    source.write_bytes(b"x" * 4096)
    (project_b / "shared.bin").hardlink_to(source)

    report = build_report(discover_candidates(tmp_path))

    assert report["deletable_candidate_bytes_upper_bound"] >= report["deletable_bytes"]


def test_human_bytes_formats_gib() -> None:
    assert human_bytes(5 * 1024**3) == "5.0 GiB"
