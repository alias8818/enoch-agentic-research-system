from __future__ import annotations

import io
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings, strategies as st

from enoch_control_plane.control_plane.safe_tar_extract import extract_safe_tar_bytes


def _tar_bytes(
    entries: dict[str, bytes],
    *,
    dirs: tuple[str, ...] = (),
    symlinks: dict[str, str] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in dirs:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        for name, target in (symlinks or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return buffer.getvalue()


def _statuses(result: dict[str, object]) -> set[str]:
    skipped = result.get("skipped")
    assert isinstance(skipped, list)
    return {str(item["status"]) for item in skipped}


def test_extract_safe_tar_bytes_extracts_regular_files(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifact"
    payload = _tar_bytes({"run_notes.md": b"safe notes"}, dirs=("results",))

    result = extract_safe_tar_bytes(payload, artifact_root)

    assert result["ok"] is True
    assert result["reason"] == "safe_tar_extracted"
    assert result["paths"] == ["run_notes.md"]
    assert (artifact_root / "run_notes.md").read_text(encoding="utf-8") == "safe notes"
    assert (artifact_root / "results").is_dir()


@pytest.mark.parametrize(
    "member_name",
    [
        "../escape.txt",
        "/absolute.txt",
        "safe/../../escape.txt",
        "",
    ],
)
def test_extract_safe_tar_bytes_rejects_unsafe_paths(
    tmp_path: Path, member_name: str
) -> None:
    artifact_root = tmp_path / "artifact"
    outside = tmp_path / "escape.txt"
    payload = _tar_bytes({member_name: b"escape"})

    result = extract_safe_tar_bytes(payload, artifact_root)

    assert result["ok"] is False
    assert result["reason"] == "no_safe_tar_evidence"
    assert "unsafe_path" in _statuses(result)
    assert not outside.exists()


@given(member_name=st.text(min_size=1, max_size=40))
@settings(max_examples=80, deadline=None)
def test_extract_safe_tar_bytes_never_writes_outside_artifact_root(
    member_name: str,
) -> None:
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        artifact_root = tmp_path / "artifact"
        outside = tmp_path / "outside-sentinel.txt"
        payload = _tar_bytes({member_name: b"content"})

        result = extract_safe_tar_bytes(payload, artifact_root)

        assert not outside.exists()
        for path in result["paths"]:
            resolved = (artifact_root / str(path)).resolve(strict=False)
            resolved.relative_to(artifact_root.resolve(strict=False))


def test_extract_safe_tar_bytes_rejects_symlink_member(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifact"
    payload = _tar_bytes({}, symlinks={"link.txt": "../outside.txt"})

    result = extract_safe_tar_bytes(payload, artifact_root)

    assert result["ok"] is False
    assert result["reason"] == "no_safe_tar_evidence"
    assert "unsafe_path" in _statuses(result)
    assert not (artifact_root / "link.txt").exists()


def test_extract_safe_tar_bytes_rejects_too_many_members(tmp_path: Path) -> None:
    payload = _tar_bytes({f"file-{index}.txt": b"x" for index in range(4)})

    result = extract_safe_tar_bytes(payload, tmp_path / "artifact", max_entries=3)

    assert result["ok"] is False
    assert result["reason"] == "extract_limit_exceeded"
    assert "too_many_members" in _statuses(result)


def test_extract_safe_tar_bytes_records_too_large_member(tmp_path: Path) -> None:
    payload = _tar_bytes({"large.bin": b"abcd"})

    result = extract_safe_tar_bytes(payload, tmp_path / "artifact", max_file_bytes=3)

    assert result["ok"] is False
    assert result["reason"] == "no_safe_tar_evidence"
    assert "too_large" in _statuses(result)


def test_extract_safe_tar_bytes_records_compression_ratio_limit(tmp_path: Path) -> None:
    payload = _tar_bytes({"zeros.bin": b"0" * 20_000})

    result = extract_safe_tar_bytes(
        payload,
        tmp_path / "artifact",
        max_compression_ratio=1,
        max_file_bytes=30_000,
        max_total_bytes=30_000,
    )

    assert result["ok"] is False
    assert result["reason"] == "extract_limit_exceeded"
    assert "compression_ratio" in _statuses(result)


def test_extract_safe_tar_bytes_reports_empty_archive(tmp_path: Path) -> None:
    payload = _tar_bytes({})

    result = extract_safe_tar_bytes(payload, tmp_path / "artifact")

    assert result == {
        "ok": False,
        "reason": "no_safe_tar_evidence",
        "files": 0,
        "paths": [],
        "skipped": [],
    }


def test_extract_safe_tar_bytes_reports_extract_failed(tmp_path: Path) -> None:
    result = extract_safe_tar_bytes(b"not a tar.gz", tmp_path / "artifact")

    assert result["ok"] is False
    assert result["reason"] == "extract_failed"
    assert "ReadError" in str(result["error"])


def test_extract_safe_tar_bytes_reports_unusable_artifact_root(tmp_path: Path) -> None:
    blocking_file = tmp_path / "artifact"
    blocking_file.write_text("not a directory", encoding="utf-8")

    result = extract_safe_tar_bytes(_tar_bytes({"run_notes.md": b"x"}), blocking_file)

    assert result["ok"] is False
    assert result["reason"] == "artifact_root_unusable"
