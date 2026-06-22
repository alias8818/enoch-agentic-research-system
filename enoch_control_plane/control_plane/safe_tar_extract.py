from __future__ import annotations

import logging

import io
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

# Sonar S5042: bound untrusted tar expansion (zip bomb / inode exhaustion).


_logger = logging.getLogger(__name__)

_MAX_TAR_ENTRIES = 512
_MAX_TAR_COMPRESSION_RATIO = 10
_TAR_READ_CHUNK_BYTES = 8192


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(content)
            tmp = Path(handle.name)
        tmp.replace(path)
    finally:
        if tmp is not None:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError as exc:
                _logger.debug(
                    "failed to remove temporary tar extraction file", exc_info=exc
                )


def _safe_tar_target(artifact_root: Path, member_name: str) -> Path | None:
    raw = PurePosixPath(str(member_name or ""))
    if (
        raw.is_absolute()
        or not raw.parts
        or any(part in {"", ".", ".."} for part in raw.parts)
    ):
        return None
    try:
        target = (artifact_root / Path(*raw.parts)).resolve()
        target.relative_to(artifact_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return target


def _append_tar_skip(
    skipped: list[dict[str, Any]], *, path: str, status: str, error: str
) -> None:
    skipped.append({"path": path, "status": status, "error": error})


def _fallback_filter_tar_member(
    member: tarfile.TarInfo, artifact_root: Path
) -> tarfile.TarInfo | None:
    """Reject unsafe tar members when PEP 706 data_filter is unavailable.

    The project supports Python 3.11, where ``tarfile.data_filter`` is not
    guaranteed to exist.  Keep the Python 3.11 path independently safe instead
    of returning unfiltered members and relying on later extraction code to
    catch links or special files.
    """
    if _safe_tar_target(artifact_root, member.name) is None:
        return None
    if member.isdir() or member.isfile():
        return member
    return None


def _filter_tar_member(
    member: tarfile.TarInfo, artifact_root: Path
) -> tarfile.TarInfo | None:
    """Apply PEP 706 data filter when available, with a safe Python 3.11 fallback."""
    data_filter = getattr(tarfile, "data_filter", None)
    if data_filter is None:
        return _fallback_filter_tar_member(member, artifact_root)
    try:
        return data_filter(member, str(artifact_root))
    except tarfile.FilterError:
        return None


def _read_tar_member_bytes(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    max_file_bytes: int,
) -> bytes | None:
    extracted = archive.extractfile(member)
    if extracted is None:
        return None
    chunks: list[bytes] = []
    size_read = 0
    declared_size = max(int(member.size or 0), 0)
    while size_read <= max_file_bytes:
        chunk = extracted.read(
            min(_TAR_READ_CHUNK_BYTES, max_file_bytes - size_read + 1)
        )
        if not chunk:
            break
        size_read += len(chunk)
        if declared_size > 0 and size_read / declared_size > _MAX_TAR_COMPRESSION_RATIO:
            return None
        chunks.append(chunk)
    if size_read > max_file_bytes:
        return None
    return b"".join(chunks)


def _extract_tar_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    artifact_root: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    written: list[str],
    skipped: list[dict[str, Any]],
    total_bytes: int,
) -> int:
    target = _safe_tar_target(artifact_root, member.name)
    if target is None:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="unsafe_path",
            error="tar member path escapes artifact root",
        )
        return total_bytes
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return total_bytes
    if not member.isfile():
        _append_tar_skip(
            skipped,
            path=member.name,
            status="unsupported_member",
            error="tar member is not a regular file",
        )
        return total_bytes
    if member.size > max_file_bytes or total_bytes + member.size > max_total_bytes:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="too_large",
            error="tar member exceeds evidence extraction byte limit",
        )
        return total_bytes
    content = _read_tar_member_bytes(archive, member, max_file_bytes=max_file_bytes)
    if content is None:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="compression_ratio",
            error="tar member exceeds safe compression ratio",
        )
        return total_bytes
    if len(content) > max_file_bytes:
        _append_tar_skip(
            skipped,
            path=member.name,
            status="too_large",
            error="tar member exceeds evidence extraction byte limit",
        )
        return total_bytes
    _atomic_write_bytes(target, content)
    written.append(member.name)
    return total_bytes + len(content)


def _tar_archive_entry_limit_reached(
    entry_count: int,
    threshold_entries: int,
    member: tarfile.TarInfo,
    skipped: list[dict[str, Any]],
) -> bool:
    if entry_count <= threshold_entries:
        return False
    _append_tar_skip(
        skipped,
        path=member.name,
        status="too_many_members",
        error="tar archive exceeds safe member count",
    )
    return True


def _tar_archive_size_limit_reached(
    total_bytes: int,
    threshold_size: int,
    member: tarfile.TarInfo,
    skipped: list[dict[str, Any]],
) -> bool:
    if total_bytes <= threshold_size:
        return False
    _append_tar_skip(
        skipped,
        path=member.name,
        status="too_large",
        error="tar archive exceeds safe total uncompressed size",
    )
    return True


def _tar_archive_ratio_limit_reached(
    total_bytes: int,
    compressed_len: int,
    threshold_ratio: int,
    member: tarfile.TarInfo,
    skipped: list[dict[str, Any]],
    *,
    require_positive_total: bool,
) -> bool:
    if require_positive_total and total_bytes <= 0:
        return False
    if total_bytes / compressed_len <= threshold_ratio:
        return False
    _append_tar_skip(
        skipped,
        path=member.name,
        status="compression_ratio",
        error="tar archive exceeds safe compression ratio",
    )
    return True


def _tar_regular_file_readable(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    skipped: list[dict[str, Any]],
) -> bool:
    if not member.isfile():
        return True
    member_stream = archive.extractfile(member)
    if member_stream is not None:
        member_stream.close()
        return True
    _append_tar_skip(
        skipped,
        path=member.name,
        status="unsupported_member",
        error="tar member is not readable as a regular file",
    )
    return False


def _extract_bounded_tar_member_with_limits(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    artifact_root: Path,
    total_bytes: int,
    compressed_len: int,
    threshold_size: int,
    threshold_ratio: int,
    max_file_bytes: int,
    written: list[str],
    skipped: list[dict[str, Any]],
) -> tuple[int, bool]:
    """Extract one filtered member; return updated total_bytes and limit_exceeded."""
    if _tar_archive_size_limit_reached(total_bytes, threshold_size, member, skipped):
        return total_bytes, True
    if _tar_archive_ratio_limit_reached(
        total_bytes,
        compressed_len,
        threshold_ratio,
        member,
        skipped,
        require_positive_total=True,
    ):
        return total_bytes, True
    if not _tar_regular_file_readable(archive, member, skipped):
        return total_bytes, False
    total_bytes = _extract_tar_member(
        archive,
        member,
        artifact_root,
        max_file_bytes=max_file_bytes,
        max_total_bytes=threshold_size,
        written=written,
        skipped=skipped,
        total_bytes=total_bytes,
    )
    if _tar_archive_size_limit_reached(total_bytes, threshold_size, member, skipped):
        return total_bytes, True
    if _tar_archive_ratio_limit_reached(
        total_bytes,
        compressed_len,
        threshold_ratio,
        member,
        skipped,
        require_positive_total=False,
    ):
        return total_bytes, True
    return total_bytes, False


def _expand_bounded_tar_gz(
    payload: bytes,
    artifact_root: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    max_entries: int,
    max_compression_ratio: int,
    written: list[str],
    skipped: list[dict[str, Any]],
) -> tuple[int, bool]:
    """Expand untrusted gzip tar with S5042 entry/size/ratio bounds (no extractall)."""
    compressed_len = max(len(payload), 1)
    total_bytes = 0
    limit_exceeded = False
    threshold_entries = max_entries
    threshold_size = max_total_bytes
    threshold_ratio = max_compression_ratio
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        data_filter = getattr(tarfile, "data_filter", None)
        if data_filter is not None:
            archive.extraction_filter = data_filter
        entry_count = 0
        for member in archive:
            entry_count += 1
            if _tar_archive_entry_limit_reached(
                entry_count, threshold_entries, member, skipped
            ):
                limit_exceeded = True
                break
            filtered = _filter_tar_member(member, artifact_root)
            if filtered is None:
                _append_tar_skip(
                    skipped,
                    path=member.name,
                    status="unsafe_path",
                    error="tar member rejected by data filter",
                )
                continue
            total_bytes, limit_exceeded = _extract_bounded_tar_member_with_limits(
                archive,
                filtered,
                artifact_root=artifact_root,
                total_bytes=total_bytes,
                compressed_len=compressed_len,
                threshold_size=threshold_size,
                threshold_ratio=threshold_ratio,
                max_file_bytes=max_file_bytes,
                written=written,
                skipped=skipped,
            )
            if limit_exceeded:
                break
    return total_bytes, limit_exceeded


def extract_safe_tar_bytes(
    payload: bytes,
    artifact_root: Path,
    *,
    max_file_bytes: int = 8_000_000,
    max_total_bytes: int = 64_000_000,
    max_entries: int = _MAX_TAR_ENTRIES,
    max_compression_ratio: int = _MAX_TAR_COMPRESSION_RATIO,
) -> dict[str, Any]:
    try:
        artifact_root = artifact_root.resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "artifact_root_unusable",
            "files": 0,
            "paths": [],
            "skipped": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    written: list[str] = []
    skipped: list[dict[str, Any]] = []
    limit_exceeded = False
    try:
        _, limit_exceeded = _expand_bounded_tar_gz(
            payload,
            artifact_root,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
            max_entries=max_entries,
            max_compression_ratio=max_compression_ratio,
            written=written,
            skipped=skipped,
        )
    except (tarfile.TarError, OSError, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "extract_failed",
            "files": len(written),
            "paths": written[:30],
            "skipped": skipped[:30],
            "error": f"{type(exc).__name__}: {exc}",
        }
    if limit_exceeded:
        return {
            "ok": False,
            "reason": "extract_limit_exceeded",
            "files": len(written),
            "paths": written[:30],
            "skipped": skipped[:30],
        }
    return {
        "ok": bool(written),
        "reason": "safe_tar_extracted" if written else "no_safe_tar_evidence",
        "files": len(written),
        "paths": written[:30],
        "skipped": skipped[:30],
    }
