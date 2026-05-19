from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import push_public_release_bundle


def repo(tmp_path: Path, key: str) -> push_public_release_bundle.Repo:
    path = tmp_path / key
    path.mkdir()
    return push_public_release_bundle.Repo(key, path)


def test_local_release_checks_run_docs_validators_before_manifest(monkeypatch, tmp_path: Path) -> None:
    system = repo(tmp_path, "enoch-agentic-research-system")
    corpus = repo(tmp_path, "enoch-ai-research-corpus")
    docs = repo(tmp_path, "enoch-docs")
    profile = repo(tmp_path, "alias8818.github.io")
    owner = repo(tmp_path, "alias8818")
    personal = repo(tmp_path, "jeremyblankenship.dev")
    promising = repo(tmp_path, "enoch-promising-signals")
    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(cmd, *, cwd=None, check=True, capture=False, env=None):
        del env
        calls.append((list(cmd), cwd))
        if any(part.endswith("generate_ecosystem_manifest.py") for part in cmd):
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "artifact_count": 377,
                        "promising_signal_count": 4,
                        "packaging_provenance_pass_count": 377,
                        "strict_claim_evidence_pass_count": 3,
                        "strict_claim_evidence_total_count": 377,
                    }
                ),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.delenv("ENOCH_SOURCE_LINEAGE_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_SUPABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(push_public_release_bundle, "run", fake_run)

    push_public_release_bundle.run_local_release_checks(system, corpus, docs, profile, owner, personal, promising)

    commands = [cmd for cmd, _cwd in calls]
    assert commands[:2] == [
        [push_public_release_bundle.sys.executable, "scripts/validate_runtime_snapshot_links.py"],
        ["node", "scripts/validate-docs.mjs"],
    ]
    assert calls[0][1] == system.path
    assert calls[1][1] == docs.path
    assert "scripts/generate_ecosystem_manifest.py" in commands[2]
    assert "--promising" in commands[2]
    assert str(promising.path) in commands[2]
    assert "scripts/validate_public_release.py" in commands[3]
    assert "--promising" in commands[3]
    assert str(promising.path) in commands[3]


def test_local_release_checks_runs_source_lineage_validator_when_database_url_is_set(monkeypatch, tmp_path: Path) -> None:
    system = repo(tmp_path, "enoch-agentic-research-system")
    corpus = repo(tmp_path, "enoch-ai-research-corpus")
    docs = repo(tmp_path, "enoch-docs")
    profile = repo(tmp_path, "alias8818.github.io")
    owner = repo(tmp_path, "alias8818")
    personal = repo(tmp_path, "jeremyblankenship.dev")
    promising = repo(tmp_path, "enoch-promising-signals")
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(cmd, *, cwd=None, check=True, capture=False, env=None):
        del cwd, check, capture
        calls.append((list(cmd), env))
        if any(part.endswith("generate_ecosystem_manifest.py") for part in cmd):
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "artifact_count": 377,
                        "promising_signal_count": 4,
                        "packaging_provenance_pass_count": 377,
                        "strict_claim_evidence_pass_count": 3,
                        "strict_claim_evidence_total_count": 377,
                    }
                ),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setenv("ENOCH_SOURCE_LINEAGE_DATABASE_URL", "postgres://validator")
    monkeypatch.setenv("ENOCH_SOURCE_LINEAGE_CREATED_AFTER", "2026-05-19T00:00:00Z")
    monkeypatch.setattr(push_public_release_bundle, "run", fake_run)

    push_public_release_bundle.run_local_release_checks(system, corpus, docs, profile, owner, personal, promising)

    commands = [cmd for cmd, _env in calls]
    assert commands[:3] == [
        [push_public_release_bundle.sys.executable, "scripts/validate_runtime_snapshot_links.py"],
        [
            push_public_release_bundle.sys.executable,
            "scripts/validate_source_lineage.py",
            "--created-after",
            "2026-05-19T00:00:00Z",
        ],
        ["node", "scripts/validate-docs.mjs"],
    ]
    assert calls[1][1] == {"ENOCH_SOURCE_LINEAGE_DATABASE_URL": "postgres://validator"}


def test_local_release_checks_stop_when_docs_validator_fails(monkeypatch, tmp_path: Path) -> None:
    system = repo(tmp_path, "enoch-agentic-research-system")
    corpus = repo(tmp_path, "enoch-ai-research-corpus")
    docs = repo(tmp_path, "enoch-docs")
    profile = repo(tmp_path, "alias8818.github.io")
    owner = repo(tmp_path, "alias8818")
    personal = repo(tmp_path, "jeremyblankenship.dev")
    promising = repo(tmp_path, "enoch-promising-signals")
    calls: list[list[str]] = []

    def fake_run(cmd, *, cwd=None, check=True, capture=False, env=None):
        del env
        calls.append(list(cmd))
        if cmd == ["node", "scripts/validate-docs.mjs"]:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.delenv("ENOCH_SOURCE_LINEAGE_DATABASE_URL", raising=False)
    monkeypatch.delenv("ENOCH_SUPABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(push_public_release_bundle, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        push_public_release_bundle.run_local_release_checks(system, corpus, docs, profile, owner, personal, promising)

    assert calls == [
        [push_public_release_bundle.sys.executable, "scripts/validate_runtime_snapshot_links.py"],
        ["node", "scripts/validate-docs.mjs"],
    ]


def test_sync_corpus_import_ledger_passes_database_url_via_env_not_argv(monkeypatch, tmp_path: Path) -> None:
    system = repo(tmp_path, "enoch-agentic-research-system")
    corpus = repo(tmp_path, "enoch-ai-research-corpus")
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(cmd, *, cwd=None, check=True, capture=False, env=None):
        del cwd, check, capture
        calls.append((list(cmd), env))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(push_public_release_bundle, "run", fake_run)

    push_public_release_bundle.sync_corpus_import_ledger(
        system,
        corpus,
        database_url="postgresql://user:secret@example/db",
        use_linked=False,
    )

    assert len(calls) == 2
    for cmd, env in calls:
        assert "postgresql://user:secret@example/db" not in " ".join(cmd)
        assert env == {"ENOCH_SUPABASE_DATABASE_URL": "postgresql://user:secret@example/db"}


def test_printable_cmd_redacts_secret_args() -> None:
    assert push_public_release_bundle.printable_cmd(["cmd", "--db-url", "postgres://secret", "--ok"]) == "cmd --db-url <redacted> --ok"
